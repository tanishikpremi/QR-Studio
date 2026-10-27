# QR Studio

A small Flask QR code generator with a live preview, PNG downloads, and a
local SQLite history. Two retro skins: an amber-phosphor terminal (default)
and Windows 98.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>.

The database is created automatically at `instance/qr_studio.db`. History
keeps the 50 most recent codes; regenerating an identical code moves it back
to the top instead of creating a duplicate.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Generator with live preview |
| `/api/generate` | POST | Validate JSON, save the code, return a data-URI preview |
| `/qr/<id>.png` | GET | Inline PNG used by history thumbnails |
| `/download/<id>` | GET | Download the saved code as a PNG |
| `/history` | GET | Saved codes |
| `/history/<id>/delete` | POST | Delete a saved code |
| `/settings` | POST | Store the theme preference in a cookie |

## Validation

- Content is required and capped at 1000 characters.
- Colors must be six-digit hex values.
- Size must be an integer between 100 and 600 px.
- `http://` and `https://` links are checked before encoding.
- Downloads are rendered in memory; no temporary files are written.

## Layout

```
app.py                  Flask app, validation, QR rendering, SQLite
requirements.txt
instance/qr_studio.db   Created on first run
templates/
  base.html             Shared shell, theme switch, navigation
  index.html            Generator and preview
  history.html          Saved codes
static/
  css/style.css         Terminal and Windows 98 skins
  js/app.js             Live preview, copy, contrast warning
  favicon.svg
```
