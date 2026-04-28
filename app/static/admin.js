(function () {
  const state = {
    apiUrl: localStorage.getItem("af_api_url") || "http://127.0.0.1:8000",
    token: localStorage.getItem("af_token") || "",
    role: localStorage.getItem("af_role") || "",
  };

  const els = {
    apiUrl: document.getElementById("apiUrl"),
    email: document.getElementById("email"),
    password: document.getElementById("password"),
    loginBtn: document.getElementById("loginBtn"),
    authStatus: document.getElementById("authStatus"),
    app: document.getElementById("app"),
    refreshBtn: document.getElementById("refreshBtn"),
    exportBtn: document.getElementById("exportBtn"),
    searchClients: document.getElementById("searchClients"),
    startDate: document.getElementById("startDate"),
    endDate: document.getElementById("endDate"),
    totalClients: document.getElementById("totalClients"),
    totalAppointments: document.getElementById("totalAppointments"),
    appointmentsToday: document.getElementById("appointmentsToday"),
    totalRevenue: document.getElementById("totalRevenue"),
    staffMetricsList: document.getElementById("staffMetricsList"),
    automationList: document.getElementById("automationList"),
    clientsList: document.getElementById("clientsList"),
    remindersList: document.getElementById("remindersList"),
    calendarList: document.getElementById("calendarList"),
    newUserName: document.getElementById("newUserName"),
    newUserEmail: document.getElementById("newUserEmail"),
    newUserPassword: document.getElementById("newUserPassword"),
    newUserRole: document.getElementById("newUserRole"),
    createUserBtn: document.getElementById("createUserBtn"),
    userStatus: document.getElementById("userStatus"),
    usersList: document.getElementById("usersList"),
    serviceName: document.getElementById("serviceName"),
    servicePrice: document.getElementById("servicePrice"),
    createServiceBtn: document.getElementById("createServiceBtn"),
    serviceStatus: document.getElementById("serviceStatus"),
    servicesList: document.getElementById("servicesList"),
  };

  const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  els.apiUrl.value = state.apiUrl;

  function api(path, options = {}) {
    return fetch(`${state.apiUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
        ...(options.headers || {}),
      },
    });
  }

  function setStatus(message) {
    els.authStatus.textContent = message;
  }

  async function login() {
    state.apiUrl = els.apiUrl.value.trim();
    localStorage.setItem("af_api_url", state.apiUrl);
    setStatus("Entrando...");
    const response = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: els.email.value.trim(),
        password: els.password.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Falha ao autenticar.");
    }
    state.token = data.access_token;
    state.role = data.role;
    localStorage.setItem("af_token", state.token);
    localStorage.setItem("af_role", state.role);
    setStatus(`Conectado em ${data.company_name} como ${data.role}.`);
    els.app.classList.remove("hidden");
    await loadDashboard();
  }

  function exportUrl() {
    const start = els.startDate.value || new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString();
    const end = els.endDate.value || new Date().toISOString();
    const params = new URLSearchParams({
      start_date: start,
      end_date: end,
      token: state.token,
    });
    return `${state.apiUrl}/exports/financial.csv?${params.toString()}`;
  }

  async function loadDashboard() {
    const search = encodeURIComponent(els.searchClients.value.trim());
    const requests = [
      api("/summary"),
      api(`/clients${search ? `?search=${search}` : ""}`),
      api("/reminders"),
      api("/services"),
    ];
    if (state.role === "admin") {
      requests.push(api("/users"));
      requests.push(api("/analytics/staff"));
      requests.push(api("/automations/reminders/preview"));
    }
    const [summaryRes, clientsRes, remindersRes, servicesRes, usersRes, staffRes, automationRes] = await Promise.all(requests);

    const summary = await summaryRes.json();
    const clients = await clientsRes.json();
    const reminders = await remindersRes.json();
    const services = await servicesRes.json();
    const users = usersRes ? await usersRes.json() : [];
    const staffMetrics = staffRes ? await staffRes.json() : [];
    const automation = automationRes ? await automationRes.json() : null;

    els.totalClients.textContent = summary.total_clients ?? 0;
    els.totalAppointments.textContent = summary.total_appointments ?? 0;
    els.appointmentsToday.textContent = summary.appointments_today ?? 0;
    els.totalRevenue.textContent = currency.format(summary.total_revenue ?? 0);

    els.clientsList.innerHTML = clients.length
      ? clients
          .map(
            (client) => `
              <div class="item">
                <strong>${client.name}</strong>
                <div class="muted">${client.phone || "Sem telefone"}</div>
              </div>`,
          )
          .join("")
      : '<div class="muted">Nenhum cliente encontrado.</div>';

    els.remindersList.innerHTML = reminders.length
      ? reminders
          .map(
            (item) => `
              <div class="item">
                <strong>${new Date(item.follow_up_date).toLocaleDateString("pt-BR")}</strong>
                <div>${item.description}</div>
                <div class="muted">${item.amount ? currency.format(item.amount) : "Sem valor"}</div>
              </div>`,
          )
          .join("")
      : '<div class="muted">Nenhum lembrete pendente.</div>';

    const groupedReminders = reminders.reduce((acc, item) => {
      const key = new Date(item.follow_up_date).toLocaleDateString("pt-BR");
      acc[key] = acc[key] || [];
      acc[key].push(item);
      return acc;
    }, {});

    const calendarEntries = Object.entries(groupedReminders);
    els.calendarList.innerHTML = calendarEntries.length
      ? calendarEntries
          .map(
            ([date, entries]) => `
              <div class="item">
                <strong>${date}</strong>
                <div class="muted">${entries.length} retorno(s)</div>
                <div style="margin-top:8px;">${entries.map((entry) => `<div>${entry.description}</div>`).join("")}</div>
              </div>`,
          )
          .join("")
      : '<div class="muted">Nenhum retorno agendado.</div>';

    els.servicesList.innerHTML = services.length
      ? services
          .map(
            (service) => `
              <div class="item">
                <strong>${service.name}</strong>
                <div class="muted">${service.default_price ? currency.format(service.default_price) : "Sem preco padrao"}</div>
              </div>`,
          )
          .join("")
      : '<div class="muted">Nenhum servico cadastrado.</div>';

    if (state.role === "admin") {
      els.staffMetricsList.innerHTML = staffMetrics.length
        ? staffMetrics
            .map(
              (item) => `
                <div class="item">
                  <strong>${item.user_name}</strong>
                  <div class="muted">Perfil: ${item.role}</div>
                  <div class="muted">${item.total_appointments} atendimento(s)</div>
                  <div class="muted">${currency.format(item.total_revenue || 0)}</div>
                </div>`,
            )
            .join("")
        : '<div class="muted">Sem indicadores ainda.</div>';
      els.automationList.innerHTML = automation
        ? `
            <div class="item"><strong>Atrasados</strong><div class="muted">${automation.late_count}</div></div>
            <div class="item"><strong>Hoje</strong><div class="muted">${automation.today_count}</div></div>
            <div class="item"><strong>Proximos 3 dias</strong><div class="muted">${automation.next_three_days_count}</div></div>
          `
        : '<div class="muted">Sem dados de automacao.</div>';
      els.usersList.innerHTML = users.length
        ? users
            .map(
              (user) => `
                <div class="item">
                  <strong>${user.name}</strong>
                  <div class="muted">${user.email}</div>
                  <div class="muted">Perfil: ${user.role}</div>
                </div>`,
            )
            .join("")
        : '<div class="muted">Nenhum usuario cadastrado.</div>';
    } else {
      els.staffMetricsList.innerHTML = '<div class="muted">Somente admin pode ver indicadores por atendente.</div>';
      els.automationList.innerHTML = '<div class="muted">Somente admin pode ver automacoes.</div>';
      els.usersList.innerHTML = '<div class="muted">Somente admin pode gerenciar usuarios.</div>';
      els.createUserBtn.disabled = true;
      els.createServiceBtn.disabled = true;
    }
  }

  async function createUser() {
    const response = await api("/users", {
      method: "POST",
      body: JSON.stringify({
        name: els.newUserName.value.trim(),
        email: els.newUserEmail.value.trim(),
        password: els.newUserPassword.value,
        role: (els.newUserRole.value.trim() || "staff").toLowerCase(),
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Falha ao criar usuario.");
    }
    els.userStatus.textContent = `Usuario ${data.name} criado com sucesso.`;
    els.newUserName.value = "";
    els.newUserEmail.value = "";
    els.newUserPassword.value = "";
    els.newUserRole.value = "staff";
    await loadDashboard();
  }

  async function createService() {
    const response = await api("/services", {
      method: "POST",
      body: JSON.stringify({
        name: els.serviceName.value.trim(),
        default_price: els.servicePrice.value ? Number(els.servicePrice.value) : null,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Falha ao criar servico.");
    }
    els.serviceStatus.textContent = `Servico ${data.name} criado com sucesso.`;
    els.serviceName.value = "";
    els.servicePrice.value = "";
    await loadDashboard();
  }

  els.loginBtn.addEventListener("click", async () => {
    try {
      await login();
    } catch (error) {
      setStatus(error.message);
    }
  });

  els.refreshBtn.addEventListener("click", () => loadDashboard().catch((error) => setStatus(error.message)));
  els.searchClients.addEventListener("input", () => loadDashboard().catch((error) => setStatus(error.message)));
  els.exportBtn.addEventListener("click", async () => {
    await navigator.clipboard.writeText(exportUrl());
    setStatus("Link da exportacao copiado.");
  });
  els.createUserBtn.addEventListener("click", () => {
    createUser().catch((error) => {
      els.userStatus.textContent = error.message;
    });
  });
  els.createServiceBtn.addEventListener("click", () => {
    createService().catch((error) => {
      els.serviceStatus.textContent = error.message;
    });
  });

  if (state.token) {
    els.app.classList.remove("hidden");
    loadDashboard().catch(() => {
      setStatus("Token salvo, mas nao foi possivel carregar. Faça login novamente.");
    });
  }
})();
