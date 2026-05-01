# 📰 Globes Daily Summarizer

מערכת אוטומטית שמסכמת את כתבות גלובס כל יום ב-07:00 ושולחת אותן במייל.

---

## דרישות מוקדמות

| דרישה | פירוט |
|---|---|
| **Python 3.10+** | [הורדה](https://www.python.org/downloads/) |
| **Claude API Key** | [console.anthropic.com](https://console.anthropic.com/) |
| **Gmail App Password** | ראה הוראות למטה |

---

## התקנה מהירה

```batch
cd C:\path\to\globes-summary
setup.bat
```

הסקריפט מבצע אוטומטית:
1. `pip install` לכל הספריות
2. בדיקת קובץ `.env`
3. רישום משימה ב-Windows Task Scheduler לריצה יומית ב-07:00

> **הרץ כ-Administrator** אם קיבלת שגיאה ביצירת המשימה.

---

## הגדרת פרטי הכניסה

ערוך את קובץ `.env`:

```env
# גלובס – רשות (לתכנים פרמיום)
GLOBES_EMAIL=your@email.com
GLOBES_PASSWORD=your_password

# Gmail – חובה
GMAIL_USER=ybashan.cpa@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   ← App Password (לא סיסמת Gmail רגילה)

# Claude API – חובה
CLAUDE_API_KEY=sk-ant-...

# מייל יעד (ברירת מחדל: GMAIL_USER)
RECIPIENT_EMAIL=ybashan.cpa@gmail.com
```

### איך יוצרים Gmail App Password?

1. כנס ל-**Google Account** → [myaccount.google.com](https://myaccount.google.com)
2. **Security** → **2-Step Verification** (חייב להיות פעיל)
3. **App passwords** (בתחתית הדף)
4. בחר `Mail` + `Windows Computer` → **Generate**
5. העתק את 16 הספרות (פורמט: `xxxx xxxx xxxx xxxx`) ל-`.env`

---

## הרצה ידנית

```batch
cd C:\path\to\globes-summary
python globes_scraper.py
```

---

## ניהול המשימה האוטומטית

```batch
# הצגת סטטוס
schtasks /query /tn "GlobesDailySummary"

# הרצה מיידית
schtasks /run /tn "GlobesDailySummary"

# עדכון שעה (לדוגמה 08:00)
schtasks /change /tn "GlobesDailySummary" /st 08:00

# מחיקה
schtasks /delete /tn "GlobesDailySummary" /f
```

---

## מבנה הקבצים

```
globes-summary/
├── globes_scraper.py   ← הסקריפט הראשי
├── .env                ← פרטי כניסה (אל תשתף!)
├── requirements.txt    ← תלויות Python
├── setup.bat           ← סקריפט התקנה
├── README.md           ← המדריך הזה
└── globes_scraper.log  ← לוג ריצות (נוצר אוטומטית)
```

---

## פורמט המייל

**נושא:** `📰 תקציר גלובס – DD/MM/YYYY`

**תוכן:**
- פסקת מבוא (נושאי היום)
- מחולק לסקציות: **ראשי · כלכלה · נדל"ן · הייטק**
- לכל כתבה: כותרת + תקציר 3–4 משפטים + קישור

---

## פתרון בעיות

| בעיה | פתרון |
|---|---|
| `CLAUDE_API_KEY not set` | ערוך `.env` והכנס את המפתח |
| `Gmail auth failed` | בדוק שה-App Password נכון ו-2FA פעיל |
| `No articles found` | גלובס שינו עיצוב – בדוק `globes_scraper.log` |
| המשימה לא נוצרת | הרץ `setup.bat` כ-Administrator |
| כתבות בתשלום מוצגות חלקית | הכנס פרטי Globes ב-`.env` |

---

## הערות אבטחה

- **אל תשתף** את `.env` – הוא מכיל מפתחות API וסיסמאות.
- הוסף `.env` ל-`.gitignore` אם אתה משתמש ב-Git.
- ה-Claude API Key חיויב לפי שימוש (~1–5 ₪ ליום, תלוי בכמות הכתבות).
