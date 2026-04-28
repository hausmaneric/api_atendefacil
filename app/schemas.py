from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_name: str
    company_name: str
    role: str


class CompanyAdminCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    admin_name: str = Field(min_length=2, max_length=120)
    admin_email: EmailStr
    password: str = Field(min_length=6, max_length=120)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=120)
    role: str = Field(pattern="^(admin|staff)$")


class UserCreateApp(UserCreate):
    pass


class CompanyOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    company_id: int
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    role: str = Field(pattern="^(admin|staff)$")
    password: str | None = Field(default=None, min_length=6, max_length=120)
    is_active: bool = True


class ClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=400)


class ClientUpdate(ClientCreate):
    pass


class ClientOut(ClientCreate):
    id: int
    company_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    default_price: float | None = None


class ServiceUpdate(ServiceCreate):
    pass


class ServiceOut(BaseModel):
    id: int
    company_id: int
    name: str
    default_price: float | None
    created_at: datetime

    class Config:
        from_attributes = True


class AppointmentCreate(BaseModel):
    client_id: int
    description: str = Field(min_length=2, max_length=2000)
    amount: float | None = None
    photo_url: str | None = Field(default=None, max_length=255)
    signature_data: str | None = None
    service_date: datetime | None = None
    follow_up_date: datetime | None = None


class AppointmentUpdate(BaseModel):
    description: str = Field(min_length=2, max_length=2000)
    amount: float | None = None
    photo_url: str | None = Field(default=None, max_length=255)
    signature_data: str | None = None
    service_date: datetime | None = None
    follow_up_date: datetime | None = None
    is_done: bool | None = None


class AppointmentOut(BaseModel):
    id: int
    company_id: int
    client_id: int
    user_id: int
    description: str
    amount: float | None
    photo_url: str | None
    signature_data: str | None
    service_date: datetime
    follow_up_date: datetime | None
    is_done: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClientHistoryOut(BaseModel):
    client: ClientOut
    appointments: list[AppointmentOut]


class SummaryOut(BaseModel):
    total_clients: int
    total_appointments: int
    total_revenue: float
    appointments_today: int


class StaffMetricOut(BaseModel):
    user_id: int
    user_name: str
    role: str
    total_appointments: int
    total_revenue: float


class ReminderAutomationOut(BaseModel):
    late_count: int
    today_count: int
    next_three_days_count: int
