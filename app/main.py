from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .auth import create_access_token, get_current_user, get_user_by_token, hash_password, require_admin, verify_password
from .db import Base, engine, get_db
from .models import Appointment, Client, Company, User
from .models import Service
from .schemas import (
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
    ClientCreate,
    ClientHistoryOut,
    ClientOut,
    ClientUpdate,
    CompanyAdminCreate,
    CompanyOut,
    LoginInput,
    SummaryOut,
    StaffMetricOut,
    Token,
    UserOut,
    UserCreate,
    ReminderAutomationOut,
    ServiceCreate,
    ServiceOut,
)

Base.metadata.create_all(bind=engine)
with engine.begin() as connection:
    try:
        connection.execute(text("ALTER TABLE appointments ADD COLUMN follow_up_date DATETIME"))
    except OperationalError:
        pass
    try:
        connection.execute(text("ALTER TABLE appointments ADD COLUMN is_done BOOLEAN DEFAULT 0"))
    except OperationalError:
        pass
    try:
        connection.execute(text("ALTER TABLE appointments ADD COLUMN signature_data TEXT"))
    except OperationalError:
        pass
    try:
        connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'staff'"))
    except OperationalError:
        pass
    try:
        connection.execute(
            text(
                "CREATE TABLE services (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL, default_price FLOAT, created_at DATETIME)"
            )
        )
    except OperationalError:
        pass

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="AtendeFacil API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/admin-assets", StaticFiles(directory=STATIC_DIR), name="admin-assets")


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_simple_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 12 Tf", "40 800 Td"]
    first = True
    for line in lines:
        safe = _pdf_escape(line[:140])
        if not first:
            content_lines.append("0 -18 Td")
        content_lines.append(f"({_pdf_escape(safe)}) Tj")
        first = False
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n")
    objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n")
    objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append(f"5 0 obj << /Length {len(stream)} >> stream\n".encode("latin-1") + stream + b"\nendstream endobj\n")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("latin-1"),
    )
    return bytes(pdf)


def _csv_escape(value: str) -> str:
    safe = value.replace('"', '""')
    return f'"{safe}"'


@app.get("/")
def root():
    return {"name": "AtendeFacil API", "status": "ok", "mode": "multi-company"}


@app.get("/admin", include_in_schema=False)
def admin_dashboard():
    return FileResponse(STATIC_DIR / "admin.html")


@app.post("/uploads")
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    company_dir = UPLOAD_DIR / str(current_user.company_id)
    company_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    destination = company_dir / filename
    destination.write_bytes(await file.read())
    return {"url": f"/uploads/{current_user.company_id}/{filename}"}


@app.post("/auth/register-company-admin", response_model=Token, status_code=status.HTTP_201_CREATED)
def register_company_admin(payload: CompanyAdminCreate, db: Session = Depends(get_db)):
    existing_company = db.query(Company).filter(func.lower(Company.name) == payload.company_name.lower()).first()
    if existing_company:
        raise HTTPException(status_code=400, detail="Company name already exists")

    existing_user = db.query(User).filter(func.lower(User.email) == payload.admin_email.lower()).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists")

    company = Company(name=payload.company_name.strip())
    db.add(company)
    db.flush()

    user = User(
        company_id=company.id,
        name=payload.admin_name.strip(),
        email=payload.admin_email.lower(),
        password_hash=hash_password(payload.password),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(str(user.id))
    return Token(access_token=token, user_name=user.name, company_name=company.name, role=user.role)


@app.post("/auth/login", response_model=Token)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(str(user.id))
    return Token(access_token=token, user_name=user.name, company_name=user.company.name, role=user.role)


@app.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing_user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(
        company_id=current_user.company_id,
        name=payload.name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return (
        db.query(User)
        .filter(User.company_id == current_user.company_id)
        .order_by(User.name.asc())
        .all()
    )


@app.get("/companies/me", response_model=CompanyOut)
def get_my_company(current_user: User = Depends(get_current_user)):
    return current_user.company


@app.get("/users/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.post("/clients", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = Client(
        company_id=current_user.company_id,
        name=payload.name.strip(),
        phone=payload.phone,
        notes=payload.notes,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@app.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(
    payload: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    service = Service(
        company_id=current_user.company_id,
        name=payload.name.strip(),
        default_price=payload.default_price,
    )
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@app.get("/services", response_model=list[ServiceOut])
def list_services(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Service)
        .filter(Service.company_id == current_user.company_id)
        .order_by(Service.name.asc())
        .all()
    )


@app.get("/clients", response_model=list[ClientOut])
def list_clients(
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Client).filter(Client.company_id == current_user.company_id)
    if search:
        query = query.filter(Client.name.ilike(f"%{search}%"))
    return query.order_by(Client.name.asc()).all()


@app.get("/clients/{client_id}", response_model=ClientHistoryOut)
def get_client_history(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    appointments = (
        db.query(Appointment)
        .filter(Appointment.client_id == client.id, Appointment.company_id == current_user.company_id)
        .order_by(Appointment.service_date.desc())
        .all()
    )
    return ClientHistoryOut(client=client, appointments=appointments)


@app.put("/clients/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    client.name = payload.name.strip()
    client.phone = payload.phone
    client.notes = payload.notes
    db.commit()
    db.refresh(client)
    return client


@app.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    db.delete(client)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/clients/{client_id}/report.pdf")
def get_client_report_pdf(
    client_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    current_user = get_user_by_token(token, db)
    client = db.query(Client).filter(Client.id == client_id, Client.company_id == current_user.company_id).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    appointments = (
        db.query(Appointment)
        .filter(Appointment.client_id == client.id, Appointment.company_id == current_user.company_id)
        .order_by(Appointment.service_date.desc())
        .all()
    )
    lines = [
        "AtendeFacil - Historico do Cliente",
        f"Cliente: {client.name}",
        f"Telefone: {client.phone or 'Nao informado'}",
        "",
    ]
    for item in appointments:
        amount = f"R$ {item.amount:.2f}" if item.amount is not None else "Sem valor"
        lines.extend(
            [
                item.service_date.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M"),
                item.description,
                amount,
                "",
            ],
        )
    pdf = _build_simple_pdf(lines)
    filename = f"cliente-{client.id}-historico.pdf"
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content=pdf, media_type="application/pdf", headers=headers)


@app.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = db.query(Client).filter(Client.id == payload.client_id, Client.company_id == current_user.company_id).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    appointment = Appointment(
        company_id=current_user.company_id,
        client_id=payload.client_id,
        user_id=current_user.id,
        description=payload.description.strip(),
        amount=payload.amount,
        photo_url=payload.photo_url,
        signature_data=payload.signature_data,
        service_date=payload.service_date or datetime.now(timezone.utc),
        follow_up_date=payload.follow_up_date,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment


@app.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    client_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Appointment).filter(Appointment.company_id == current_user.company_id)
    if client_id is not None:
        query = query.filter(Appointment.client_id == client_id)
    return query.order_by(Appointment.service_date.desc()).all()


@app.put("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id, Appointment.company_id == current_user.company_id)
        .first()
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appointment.description = payload.description.strip()
    appointment.amount = payload.amount
    appointment.photo_url = payload.photo_url
    appointment.signature_data = payload.signature_data
    if payload.service_date is not None:
        appointment.service_date = payload.service_date
    appointment.follow_up_date = payload.follow_up_date
    if payload.is_done is not None:
        appointment.is_done = payload.is_done
    db.commit()
    db.refresh(appointment)
    return appointment


@app.delete("/appointments/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id, Appointment.company_id == current_user.company_id)
        .first()
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    db.delete(appointment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/reminders", response_model=list[AppointmentOut])
def list_reminders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Appointment)
        .filter(Appointment.company_id == current_user.company_id, Appointment.follow_up_date.is_not(None), Appointment.is_done.is_(False))
        .order_by(Appointment.follow_up_date.asc())
        .all()
    )


@app.post("/appointments/{appointment_id}/complete", response_model=AppointmentOut)
def complete_appointment_reminder(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id, Appointment.company_id == current_user.company_id)
        .first()
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appointment.is_done = True
    db.commit()
    db.refresh(appointment)
    return appointment


@app.get("/clients/{client_id}/appointments", response_model=list[AppointmentOut])
def list_client_appointments(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Appointment)
        .filter(Appointment.client_id == client_id, Appointment.company_id == current_user.company_id)
        .order_by(Appointment.service_date.desc())
        .all()
    )


@app.get("/summary", response_model=SummaryOut)
def get_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = datetime.now(timezone.utc).date()
    total_clients = db.query(func.count(Client.id)).filter(Client.company_id == current_user.company_id).scalar() or 0
    total_appointments = db.query(func.count(Appointment.id)).filter(Appointment.company_id == current_user.company_id).scalar() or 0
    total_revenue = db.query(func.coalesce(func.sum(Appointment.amount), 0)).filter(Appointment.company_id == current_user.company_id).scalar() or 0
    appointments_today = (
        db.query(func.count(Appointment.id))
        .filter(Appointment.company_id == current_user.company_id, func.date(Appointment.service_date) == today.isoformat())
        .scalar()
        or 0
    )
    return SummaryOut(
        total_clients=int(total_clients),
        total_appointments=int(total_appointments),
        total_revenue=float(total_revenue),
        appointments_today=int(appointments_today),
    )


@app.get("/analytics/staff", response_model=list[StaffMetricOut])
def get_staff_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    rows = (
        db.query(
            User.id,
            User.name,
            User.role,
            func.count(Appointment.id).label("total_appointments"),
            func.coalesce(func.sum(Appointment.amount), 0).label("total_revenue"),
        )
        .outerjoin(Appointment, Appointment.user_id == User.id)
        .filter(User.company_id == current_user.company_id)
        .group_by(User.id, User.name, User.role)
        .order_by(func.coalesce(func.sum(Appointment.amount), 0).desc(), User.name.asc())
        .all()
    )
    return [
        StaffMetricOut(
            user_id=row.id,
            user_name=row.name,
            role=row.role,
            total_appointments=int(row.total_appointments or 0),
            total_revenue=float(row.total_revenue or 0),
        )
        for row in rows
    ]


@app.get("/automations/reminders/preview", response_model=ReminderAutomationOut)
def get_reminder_automation_preview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    today_end = today_start.replace(hour=23, minute=59, second=59)
    next_three_end = today_start.replace(hour=23, minute=59, second=59) + timedelta(days=3)

    base_query = db.query(Appointment).filter(
        Appointment.company_id == current_user.company_id,
        Appointment.follow_up_date.is_not(None),
        Appointment.is_done.is_(False),
    )
    late_count = base_query.filter(Appointment.follow_up_date < today_start).count()
    today_count = base_query.filter(Appointment.follow_up_date >= today_start, Appointment.follow_up_date <= today_end).count()
    next_three_days_count = base_query.filter(
        Appointment.follow_up_date > today_end,
        Appointment.follow_up_date <= next_three_end,
    ).count()
    return ReminderAutomationOut(
        late_count=int(late_count),
        today_count=int(today_count),
        next_three_days_count=int(next_three_days_count),
    )


@app.get("/exports/financial.csv")
def export_financial_csv(
    start_date: str = Query(...),
    end_date: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    current_user = get_user_by_token(token, db)
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    appointments = (
        db.query(Appointment, Client)
        .join(Client, Client.id == Appointment.client_id)
        .filter(
            Appointment.company_id == current_user.company_id,
            Appointment.service_date >= start,
            Appointment.service_date <= end,
        )
        .order_by(Appointment.service_date.asc())
        .all()
    )

    rows = ["data,cliente,descricao,valor,retorno,concluido"]
    for appointment, client in appointments:
        rows.append(
            ",".join(
                [
                    _csv_escape(appointment.service_date.strftime("%Y-%m-%d %H:%M")),
                    _csv_escape(client.name),
                    _csv_escape(appointment.description),
                    _csv_escape("" if appointment.amount is None else f"{appointment.amount:.2f}"),
                    _csv_escape("" if appointment.follow_up_date is None else appointment.follow_up_date.strftime("%Y-%m-%d")),
                    _csv_escape("sim" if appointment.is_done else "nao"),
                ],
            ),
        )

    content = "\n".join(rows)
    headers = {"Content-Disposition": 'attachment; filename="financeiro.csv"'}
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)
