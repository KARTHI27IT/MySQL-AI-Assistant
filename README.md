# 🗄️ MySQL AI Assistant

**Natural Language → SQL → Validate → Execute → Rollback**

---

## 📌 Overview

MySQL AI Assistant is a full-stack application that allows users to interact with a MySQL database using **natural language queries**. It converts user input into SQL, validates it, executes it safely, and even provides a **rollback mechanism** for write operations.

This project bridges the gap between **non-technical users and databases**, making data interaction intuitive, safe, and efficient.

---

## 🚀 Why This Project?

Traditional database interaction requires strong SQL knowledge. This project solves several real-world problems:

* ❌ Users struggle with writing correct SQL queries
* ❌ Risk of accidental data loss (DELETE/UPDATE without WHERE)
* ❌ No easy undo mechanism in SQL
* ❌ Complex database schemas are hard to understand

### ✅ Solution

* Use **AI to generate SQL from plain English**
* Add **validation layer** to prevent unsafe queries
* Provide **preview before execution**
* Enable **rollback within 5 minutes**

---

## 🧠 Key Features

### 🔹 1. Natural Language to SQL

* Ask questions like:

  * *"Show top 5 customers by revenue"*
* Automatically generates SQL queries

### 🔹 2. SQL Validation System

* Checks:

  * Syntax correctness
  * Dangerous operations
* Auto-corrects queries when possible

### 🔹 3. Safe Write Operations

* Requires **user confirmation**
* Shows:

  * Affected rows count
  * Sample preview of changes

### 🔹 4. Rollback System 

* Undo INSERT, UPDATE, DELETE
* Available for **5 minutes after execution**
* Stores previous state securely

### 🔹 5. Insert Modal UI

* GUI form to insert rows
* Auto-detects:

  * Data types
  * Nullable fields
  * Default values

### 🔹 6. Schema Awareness

* Improves query generation accuracy
* Helps AI understand table relationships

### 🔹 7. Result Visualization

* Clean table UI
* Pagination support
* Export results as CSV

---

## 🏗️ Tech Stack

### 🎨 Frontend

* React.js
* Tailwind CSS
* Axios
* Custom UI Components

### ⚙️ Backend

* FastAPI (Python)
* MySQL Connector
* CrewAI (AI Agents)
* LLM (Groq / LLaMA)

### 🧠 AI Layer

* SQL Generator Agent
* SQL Validator Agent
* Query Execution Controller

### 🗄️ Database

* MySQL



## ⚙️ System Architecture

<img width="1024" height="1536" alt="image" src="https://github.com/user-attachments/assets/9796465c-55f1-4ea1-b702-2b4ce4ac4ea2" />


---

## 🔄 Workflow

### 🟢 Read Query Flow

```
User → Enter Question
     → SQL Generated
     → Validated
     → Executed
     → Results Displayed
```

### 🔴 Write Query Flow

```
User → Enter Query
     → SQL Generated
     → Validation
     → Preview Impact
     → User Confirms
     → Execute Query
     → Save Previous State
     → Enable Rollback
```

### 🔁 Rollback Flow

```
User clicks Rollback
     → Fetch Stored State
     → Generate Reverse SQL
     → Execute Undo Query
```

---

## 🖼️ UI Screens (Placeholders)

### 💬 Chat Interface

```
[ User ] → Show all employees
[ AI   ] → SQL Generated + Table Output
```

### ⚠️ Confirmation Modal

```
⚠️ Confirm UPDATE Operation
- Rows affected: 5
- Preview data
[ ] I understand
[ Execute ]
```

### ➕ Insert Modal

```
Select Table → Fill Form → Insert Row
```

### ↩️ Rollback Option

```
✅ Operation Successful
↩️ Rollback Available (5m 0s)
```

---
## 🔐 Safety Features

* ✅ SQL validation before execution
* ✅ Write confirmation required
* ✅ Limited rollback window (5 min)
* ✅ Max rows cap for rollback
* ✅ Dangerous queries blocked

---

## 📊 Example Queries

| Natural Language      | Generated SQL                              |
| --------------------- | ------------------------------------------ |
| Show all users        | SELECT * FROM users;                       |
| Delete inactive users | DELETE FROM users WHERE status='inactive'; |
| Add new customer      | INSERT INTO customers (...) VALUES (...);  |

---

## 🛠️ Installation

### 1️⃣ Clone Repository

```bash
git clone https://github.com/your-repo/mysql-ai-assistant.git
cd mysql-ai-assistant
```

### 2️⃣ Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

### 3️⃣ Configure Environment

Create `.env` file:

```
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=yourpassword
GROQ_API_KEY=your_api_key
```

### 4️⃣ Run Backend

```bash
uvicorn main:app --reload
```

### 5️⃣ Frontend Setup

```bash
cd frontend
npm install
npm start
```



## 🎯 Use Cases

* Data analysts
* Non-technical business users
* Database administrators
* Educational tools for SQL learning

---

