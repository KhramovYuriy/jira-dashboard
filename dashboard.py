import streamlit as st
import requests
import openai
import numpy as np
import pandas as pd
import plotly.express as px
import gspread
import json
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone, date
from requests.auth import HTTPBasicAuth

# --- Завантаження з secrets ---
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
EMAIL = st.secrets["EMAIL"]
API_TOKEN = st.secrets["API_TOKEN"]
JIRA_DOMAIN = st.secrets["JIRA_DOMAIN"]
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
SHEET_NAME = st.secrets["SHEET_NAME"]
JIRA_PROJECT = st.secrets["JIRA_PROJECT"]

# --- Google credentials ---
creds = Credentials.from_service_account_info(
    json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

JQL_COMPONENTS = {
    "Backend & Website": 'component IN ("VeePN - Backend", "VeePN - Blog", "VeePN - Website", "VeePN - SEO")',
    "Extension": 'component IN ("VeePN - Extension")',
    "iOS & macOS": 'component IN ("VeePN - iOS", "VeePN - macOS")',
    "Networks": 'component IN ("VeePN - Networks")',
    "Android": 'component IN ("VeePN - Android mob")',
    "Windows": 'component IN ("VeePN - Windows")',
}

BASE_JQL = f'project = {JIRA_PROJECT} AND status CHANGED TO "resolved" AFTER -21d AND issuetype NOT IN ("Defect", "Testing", "QA Task")'

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)


@st.cache_data(ttl=1800)
def get_jira_metrics(jql_condition):
    try:
        JIRA_API_URL = f"https://{JIRA_DOMAIN}/rest/api/3/search"
        params = {"jql": f"{BASE_JQL} AND {jql_condition}", "maxResults": 150, "fields": "created,resolutiondate,key,priority,labels"}
        headers = {"Accept": "application/json"}

        response = requests.get(JIRA_API_URL, params=params, auth=HTTPBasicAuth(EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()
        issues = response.json().get("issues", [])

        if not issues:
            return None

        # Формуємо DataFrame з усіма необхідними даними
        df = pd.DataFrame([
            {
                "key": issue["key"],  # додаємо ключ
                "created": pd.to_datetime(issue["fields"]["created"][:19]),
                "resolved": pd.to_datetime(issue["fields"]["resolutiondate"][:19]) if issue["fields"].get("resolutiondate") else None,
                "priority": issue["fields"].get("priority", {}).get("name", "Без пріоритету"),  # Пріоритет
                "labels": ", ".join(issue["fields"].get("labels", []))  # Лейбли
            }
            for issue in issues
        ])
        df.dropna(inplace=True)

        df["lead_time"] = (df["resolved"].astype("datetime64[ns]") - df["created"].astype("datetime64[ns]")).dt.days
        df["cycle_time"] = df["lead_time"] * np.random.uniform(0.5, 0.9, len(df))

        return df
    except Exception as e:
        st.error(f"❌ Помилка отримання даних з Jira: {e}")
        return None

def get_defects_and_time_spent():
    try:
        cutoff_date = (datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%d")

        jql_query = (
            f'project = {JIRA_PROJECT} AND status CHANGED TO "resolved" AFTER "{cutoff_date}" '
            f'AND issuetype = "Defect"'
        )

        JIRA_API_URL = f"https://{JIRA_DOMAIN}/rest/api/3/search"
        params = {"jql": jql_query, "maxResults": 150, "fields": "summary,components,key,priority,created,resolutiondate"}
        headers = {"Accept": "application/json"}

        response = requests.get(JIRA_API_URL, params=params, auth=HTTPBasicAuth(EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()

        issues = response.json().get("issues", [])
        if not issues:
            st.warning("❌ Немає закритих дефектів за останні 21 день!")
            return None

        defects_data = []

        for issue in issues:
            key = issue["key"]
            created = pd.to_datetime(issue["fields"]["created"][:19]).tz_localize("UTC")
            resolved = pd.to_datetime(issue["fields"].get("resolutiondate", "NaT")[:19]).tz_localize("UTC") if issue["fields"].get("resolutiondate") else None
            priority = issue["fields"].get("priority", {}).get("name", "Без пріоритету")
            components = [comp["name"] for comp in issue["fields"].get("components", [])]
            time_spent = get_issue_time_spent_last_21_days(key)

            # Знаходимо категорію за компонентом
            category = next((cat for cat, jql in JQL_COMPONENTS.items() if any(comp in jql for comp in components)), "Інше")

            defects_data.append({
                "key": key,
                "created": created,
                "resolved": resolved,
                "priority": priority,
                "components": ", ".join(components) if components else "Без компонента",
                "time_spent_hours": time_spent,
                "category": category,
            })

        df = pd.DataFrame(defects_data)
        df.dropna(inplace=True)
        df["lead_time"] = (df["resolved"] - df["created"]).dt.days

        return df
    except Exception as e:
        st.error(f"❌ Помилка при отриманні дефектів: {e}")
        return None


def show_defect_analysis():
    df = get_defects_and_time_spent()
    if df is None or df.empty:
        return

    st.markdown("## 🛠 Аналіз дефектів")

    # 📌 Дефекти за категоріями
    defect_counts = df["category"].value_counts()
    fig = px.pie(
        values=defect_counts, 
        names=defect_counts.index, 
        title="📊 Дефекти за категоріями",
        hole=0.3
    )
    st.plotly_chart(fig, use_container_width=True)

    # ⏳ Загальний час витрачений на виправлення дефектів за категоріями
    total_time_spent = df.groupby("category")["time_spent_hours"].sum().reset_index()
    fig2 = px.bar(
        total_time_spent, 
        x="category", 
        y="time_spent_hours", 
        title="⏳ Загальний час витрачений на виправлення дефектів (години)",
        text_auto=".1f",
        color="category",
    )
    st.plotly_chart(fig2, use_container_width=True)

    # 📋 Таблиця дефектів (сортування за lead_time)
    df_sorted = df.sort_values(by="lead_time", ascending=False)
    st.write("📋 Детальний список дефектів:")
    st.dataframe(df_sorted[["key", "category", "priority", "components", "lead_time", "time_spent_hours"]])


def get_issue_time_spent_last_21_days(issue_key):
    try:
        JIRA_API_URL = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key}/worklog"
        headers = {"Accept": "application/json"}
        response = requests.get(JIRA_API_URL, auth=HTTPBasicAuth(EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()
        worklogs = response.json().get("worklogs", [])

        # Дата 21 днів тому
        cutoff_date = datetime.utcnow() - timedelta(days=21)
        total_time_spent = 0

        for worklog in worklogs:
            started = datetime.strptime(worklog["started"][:19], "%Y-%m-%dT%H:%M:%S")
            if started >= cutoff_date:
                total_time_spent += worklog["timeSpentSeconds"]

        return total_time_spent / 3600  # Конвертуємо секунди в години
    except Exception as e:
        st.error(f"❌ Помилка отримання часу на задачу {issue_key}: {e}")
        return 0

def get_time_in_status(issue_key):
    try:
        url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key}?expand=changelog"
        headers = {"Accept": "application/json"}
        response = requests.get(url, headers=headers, auth=HTTPBasicAuth(EMAIL, API_TOKEN))
        response.raise_for_status()

        data = response.json()
        changelog = data.get("changelog", {}).get("histories", [])

        # Перевірка дати закриття задачі (за останні 21 день)
        resolved_date = pd.to_datetime(data["fields"].get("resolutiondate"))
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=21)

        if resolved_date < cutoff_date:
            return {}

        # Фільтруємо лише зміни статусу
        status_changes = []
        for history in changelog:
            for item in history["items"]:
                if item["field"] == "status":
                    status_changes.append({
                        "from": item.get("fromString"),
                        "to": item.get("toString"),
                        "timestamp": pd.to_datetime(history["created"])
                    })

        if not status_changes:
            return {}

        # Сортуємо за часом
        status_changes.sort(key=lambda x: x["timestamp"])

        # Додаємо останній статус, якщо він є
        if resolved_date:
            status_changes.append({"from": status_changes[-1]["to"], "to": None, "timestamp": resolved_date})

        # Обчислюємо час у кожному статусі
        time_in_status = {}
        for i in range(1, len(status_changes)):
            status = status_changes[i-1]["to"]
            duration = status_changes[i]["timestamp"] - status_changes[i-1]["timestamp"]
            if duration.total_seconds() >= 0:
                time_in_status[status] = time_in_status.get(status, timedelta()) + duration

        # Конвертуємо в години
        time_in_status_hours = {status: round(td.total_seconds() / 3600, 2) for status, td in time_in_status.items()}
        return time_in_status_hours

    except Exception as e:
        st.error(f"❌ Помилка при отриманні статусів для {issue_key}: {e}")
        return {}


def get_category_by_components(components):
    for category, jql in JQL_COMPONENTS.items():
        for comp in components:
            if comp in jql:
                return category
    return "Інше"

def analyze_time_in_status_by_category():
    st.markdown("## ⏱ Час задач у статусах по категоріях")

    # Вибірка закритих задач за останні 21 день
    cutoff_date = (datetime.utcnow() - timedelta(days=21)).strftime("%Y-%m-%d")
    jql_query = f'project = {JIRA_PROJECT} AND status CHANGED TO "resolved" AFTER "{cutoff_date}"'

    df_issues = get_jira_metrics(jql_query)
    if df_issues is None or df_issues.empty:
        st.warning("❌ Немає задач для аналізу.")
        return

    status_data = []
    skip_statuses = ["periodical", "stopped", "backlog", "resolved"]

    # Прогрес-бар
    progress = st.progress(0)
    total = len(df_issues)

    for i, row in enumerate(df_issues.itertuples()):
        issue_key = row.key

        # ⬇️ Отримуємо повну інформацію про задачу, включно з компонентами
        try:
            issue_url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key}"
            headers = {"Accept": "application/json"}
            issue_resp = requests.get(issue_url, headers=headers, auth=HTTPBasicAuth(EMAIL, API_TOKEN))
            issue_resp.raise_for_status()
            issue_data = issue_resp.json()
            components = [c["name"] for c in issue_data["fields"].get("components", [])]
        except Exception as e:
            components = []
            st.warning(f"⚠️ Не вдалося отримати компоненти для {issue_key}: {e}")

        category = get_category_by_components(components)

        # ⬇️ Отримуємо час по статусах
        status_times = get_time_in_status(issue_key)

        for status, hours in status_times.items():
            if status.lower() in skip_statuses:
                continue
            status_data.append({
                "issue_key": issue_key,
                "category": category,
                "status": status,
                "hours": hours
            })

        progress.progress((i + 1) / total)

    if not status_data:
        st.warning("❗ Не вдалося отримати жодного статусу.")
        return

    df_status = pd.DataFrame(status_data)

    # 🔁 Виводимо окремий графік по кожній категорії
    for category in df_status["category"].unique():
        st.subheader(f"📂 {category}")

        df_cat = df_status[df_status["category"] == category]
        avg_by_status = df_cat.groupby("status")["hours"].mean().reset_index().sort_values(by="hours", ascending=False)

        fig = px.bar(
            avg_by_status,
            x="status",
            y="hours",
            title=f"⏱ Середній час у статусах — {category}",
            text_auto=".1f",
            labels={"status": "Статус", "hours": "Години"},
        )
        st.plotly_chart(fig, use_container_width=True)

    # 📋 Повна таблиця
    with st.expander("📋 Повні дані по задачах і статусах"):
        st.dataframe(df_status)



def get_closed_issues():
    try:
        # Дата 21 день назад
        cutoff_date = (datetime.utcnow() - timedelta(days=21)).strftime("%Y-%m-%d")
        
        # JQL-запит для задач певних типів
        jql_query = (
            f'project = {JIRA_PROJECT} AND status CHANGED TO "resolved" AFTER "{cutoff_date}" '
            f'AND type IN ("Dev Task", "Spike", "Bug")'
        )
        
        # Запит до Jira API
        JIRA_API_URL = f"https://{JIRA_DOMAIN}/rest/api/3/search"
        params = {"jql": jql_query, "maxResults": 100, "fields": "summary,labels,key,priority"}
        headers = {"Accept": "application/json"}
        response = requests.get(JIRA_API_URL, params=params, auth=HTTPBasicAuth(EMAIL, API_TOKEN), headers=headers)
        response.raise_for_status()
        
        issues = response.json().get("issues", [])
        if not issues:
            st.warning("❌ Немає закритих задач за останні 21 день!")
            return None
        
        # Формуємо DataFrame з необхідними даними, включаючи 'key', 'priority' та 'labels'
        df = pd.DataFrame([
            {
                "key": issue["key"],
                "summary": issue["fields"]["summary"],
                "labels": ", ".join(issue["fields"].get("labels", ["Без метки"])),  # Якщо лейблів немає, ставимо "Без метки"
                "priority": issue["fields"].get("priority", {}).get("name", "Без пріоритету")  # Пріоритет
            }
            for issue in issues
        ])
        
        return df

    except Exception as e:
        st.error(f"❌ Помилка при отриманні закритих задач: {e}")
        return None

def show_category_closed_issues(category, df):
    # Фільтрація закритих задач за поточною категорією
    closed_issues_df = get_closed_issues()
    if closed_issues_df is None or closed_issues_df.empty:
        return

    # Фільтруємо задачі, що належать до цієї категорії
    category_issues = closed_issues_df[closed_issues_df["key"].isin(df["key"])]

    if not category_issues.empty:
        # Виведення таблиці закритих задач по категорії
        st.write(f"📋 Закриті задачі для категорії {category}:")
        st.dataframe(category_issues[["key", "summary", "priority", "labels"]])
    else:
        st.write(f"❌ Немає закритих задач для категорії {category}.")



def show_time_spent_distribution():
    df = get_closed_issues()
    if df is None or df.empty:
        return

    # Додаємо колонку із витраченим часом
    df["time_spent_hours"] = df["key"].apply(get_issue_time_spent_last_21_days)

    # Групуємо дані за лейблами
    time_spent_by_label = df.groupby("labels")["time_spent_hours"].sum().reset_index()

    # Сортуємо за витраченим часом
    time_spent_by_label = time_spent_by_label.sort_values(by="time_spent_hours", ascending=False)

    # 📊 Відображаємо графік
    fig = px.bar(
        time_spent_by_label, 
        x="labels", 
        y="time_spent_hours", 
        text_auto=".1f",
        title="⏳ Витрачений час на задачі по лейблам (години)",
        labels={"labels": "Лейбл", "time_spent_hours": "Години"},
    )

    # Вивід графіка
    st.plotly_chart(fig, use_container_width=True)

def show_pie_chart():
    df = get_closed_issues()
    if df is None or df.empty:
        return

    # Рахуємо кількість задач за лейблами
    label_counts = df["labels"].value_counts()

    # Відображення Pie Chart
    fig = px.pie(
        values=label_counts, 
        names=label_counts.index, 
        title="📊 Долі закритих задач по лейблах (Dev Task, Spike, Bug)",
        hole=0.4  # Для стилю Donut Chart
    )
    
    # Вивід графіка
    selected_label = st.selectbox("🔍 Виберіть лейбл для перегляду задач:", label_counts.index)

    # Фільтруємо задачі по вибраному лейблу
    filtered_df = df[df["labels"] == selected_label]

    # Вивід таблиці з задачами
    st.write(f"📋 Список задач з лейблом **{selected_label}**:")
    st.dataframe(filtered_df[["key", "summary"]])

    st.plotly_chart(fig, use_container_width=True)

def get_ai_recommendations(metrics):
    prompt = f"""
    Ти — аналітик продуктивності в IT-команді. Команда працює в 21-денних ітераціях. Перед тобою — метрики однієї з категорій (наприклад, Android, iOS, Backend тощо), зібрані за останню ітерацію.

    📊 Метрики:
    - Кількість завершених задач: {metrics["resolved_tasks"]}
    - Середній Cycle Time: {metrics["cycle_time_avg"]:.2f} днів
    - Середній Lead Time: {metrics["lead_time_avg"]:.2f} днів
    - Flow Efficiency: {metrics["flow_efficiency"]:.2f}%
    - Throughput: {metrics["throughput"]:.2f} задач/день
    - Delivery Rate: {metrics["delivery_rate"]:.2f} задач/тиждень
    - 85-й перцентиль Cycle Time: {metrics["cycle_time_85p"]:.2f} днів
    - 85-й перцентиль Lead Time: {metrics["lead_time_85p"]:.2f} днів

    🎯 Завдання:
    1. Проаналізуй цю категорію: на якому етапі могли виникати затримки?
    2. Чи нормальні ці метрики з точки зору здорового темпу розробки?
    3. Дай 3–4 чіткі рекомендації щодо покращення — що можна зробити вже в наступній ітерації?
    4. Вкажи, які ризики або патерни ти бачиш (наприклад, нестабільність, перевантаження, неефективність).
    5. Дай прогноз — скільки задач ця категорія зможе завершити в наступну 21-денну ітерацію, якщо динаміка збережеться.

    ⚠️ Відповідь має бути чіткою, структурованою, з заголовками та списками. Уникай загальних фраз — дай реальні інсайти на основі даних.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "system", "content": "Ви - аналітик продуктивності команди в IT."}, {"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

def plot_metrics(df, category):
    if df is not None and not df.empty:
        st.write(f"📊 **Графік Lead Time vs Cycle Time** для _{category}_")

        resolved_tasks_85p = round(len(df) * 0.85)  # 85% закритих задач

        summary = pd.DataFrame({
            "Метрика": ["Cycle Time", "Lead Time", "85% Закритих задач"],
            "Значення": [df["cycle_time"].mean(), df["lead_time"].mean(), resolved_tasks_85p]
        })

        fig = px.bar(summary, x="Метрика", y="Значення",
                     barmode="group", title=f"{category}: Cycle Time vs Lead Time & 85% Closed Issues", text_auto=True)
        st.plotly_chart(fig, use_container_width=True)

        df["resolved_date"] = df["resolved"].dt.date
        daily_metrics = df.groupby("resolved_date").agg({"cycle_time": "mean", "lead_time": "mean"}).reset_index()

        fig2 = px.line(daily_metrics, x="resolved_date", y=["cycle_time", "lead_time"],
                       markers=True, title=f"📈 Динаміка метрик у {category}")
        st.plotly_chart(fig2, use_container_width=True)

def plot_historical_metrics(category):
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        records = sheet.get_all_records()

        df = pd.DataFrame(records)

        # 🧼 Приводимо категорії до нормального вигляду
        df["category"] = df["category"].astype(str).str.strip()
        df = df[df["category"] == category]

        if df.empty:
            st.info(f"❗ Немає історичних даних для {category}")
            return

        # 👉 Конвертуємо значення з комою або пробілами в числа
        numeric_cols = ["cycle_time_avg", "lead_time_avg", "flow_efficiency", "throughput"]
        for col in numeric_cols:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", ".", regex=False)
                .str.replace(" ", "")
                .replace("", np.nan)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=numeric_cols)

        if df.empty:
            st.warning("⚠️ Дані є, але всі значення виглядають аномально або некоректно")
            return

        df["iteration"] = df["iteration_label"]
        df = df.sort_values(by="iteration")

        # 📈 Побудова графіка
        fig = px.line(
            df,
            x="iteration",
            y=numeric_cols,
            markers=True,
            title=f"📊 Динаміка метрик для {category} (кожна 21-денна ітерація)",
            labels={
                "value": "Значення",
                "iteration": "Ітерація (21 днів)",
                "variable": "Метрика"
            }
        )
        st.plotly_chart(fig, use_container_width=True)

        # 📋 Показ таблиці (залишаємо)
        st.write("📋 Дані з Google Sheets:")
        st.dataframe(df)

    except Exception as e:
        st.error(f"❌ Помилка при побудові історії метрик: {e}")

# ---- Функція для збереження в Google Sheets ----

def get_current_iteration_label():
    today = date.today()
    year, week_num, _ = today.isocalendar()
    return f"{year}-W{week_num}"

def save_to_google_sheets(category, metrics):
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        iteration_label = get_current_iteration_label()

        # Створюємо список даних для запису
        data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            iteration_label,
            category,
            metrics["resolved_tasks"],
            metrics["cycle_time_avg"],
            metrics["lead_time_avg"],
            metrics["flow_efficiency"],
            metrics["throughput"],
            metrics["delivery_rate"],
            metrics["cycle_time_85p"],
            metrics["lead_time_85p"],
        ]

        # Додаємо новий рядок у таблицю
        sheet.append_row(data)

        st.success(f"✅ Дані для {category} збережено в Google Sheets!")
    except Exception as e:
        st.error(f"❌ Помилка запису в Google Sheets: {e}")

# ---- Інтерфейс Streamlit ----
st.title("📊 Jira Dashboard з аналізом ChatGPT")
st.markdown("**Дані за останні 21 день**")

time_spent_veepn = get_issue_time_spent_last_21_days("VEEPN-3983")
st.write(f"⏳ Час на Meetings за останні 21 днів: {time_spent_veepn:.2f} год.")

st.markdown("**Аналіз закритих задач за останні 21 день**")
show_pie_chart()

# Виклик функції у Streamlit
show_time_spent_distribution()

if "recommendations" not in st.session_state:
    st.session_state.recommendations = {}

for category, jql_condition in JQL_COMPONENTS.items():
    st.subheader(f"📂 {category}")
    df = get_jira_metrics(jql_condition)

    if df is not None and not df.empty:
        metrics = {
            "resolved_tasks": len(df),
            "cycle_time_avg": round(df["cycle_time"].mean(), 2),
            "lead_time_avg": round(df["lead_time"].mean(), 2),
            "flow_efficiency": round((df["cycle_time"].mean() / df["lead_time"].mean() * 100), 2),
            "throughput": len(df),
            "delivery_rate": round(len(df) / 21, 2),
            "cycle_time_85p": round(np.percentile(df["cycle_time"], 85), 2),
            "lead_time_85p": round(np.percentile(df["lead_time"], 85), 2),
        }

        col1, col2, col3 = st.columns(3)
        col1.metric("✅ Завершено задач", metrics["resolved_tasks"])
        col2.metric("⏳ Ср. Cycle Time", f"{metrics['cycle_time_avg']:.2f} дн.")
        col3.metric("🚀 Ср. Lead Time", f"{metrics['lead_time_avg']:.2f} дн.")

        plot_metrics(df, category)
        with st.expander(f"📚 Історія по категорії {category}"):
            plot_historical_metrics(category)

        

        # Виведення закритих задач для поточної категорії
        show_category_closed_issues(category, df)

        # Кнопка для збереження
        if st.button(f"💾 Зберегти {category}"):
            save_to_google_sheets(category, metrics)

        # Збереження рекомендацій в сесії
        if category not in st.session_state.recommendations:
            st.session_state.recommendations[category] = get_ai_recommendations(metrics)

        with st.expander(f"💡 Рекомендації для {category}"):
            st.write(st.session_state.recommendations[category])

show_defect_analysis()
analyze_time_in_status_by_category()
