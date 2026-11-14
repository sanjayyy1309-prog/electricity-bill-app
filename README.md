# Electricity Consumption and Bill Calculator (with Backend)

Capstone project: the original C program's logic (appliance units + slab tariff + fixed charge)
rebuilt as a web application with a **Python FastAPI** backend and a **SQLite** database.

## Run
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://127.0.0.1:8000  (API docs: http://127.0.0.1:8000/docs)

## C program -> application mapping
| C program | Application |
|---|---|
| `scanf` + validation | Pydantic models (watts > 0, quantity > 0, hours 0-24) + form checks |
| Module 1: units | `appliance_units()` in `main.py` |
| Module 2: `calculateEnergyCharge` | `slab_breakdown()` / `calculate()` |
| `fopen("bill.txt","a")` | SQLite table `bills` (`bills.db`) |
| `bill.txt` format | `GET /api/bills/export` |

## REST API
| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/calculate | Units and bill, not saved |
| POST | /api/bills | Calculate and save |
| GET | /api/bills | List saved bills |
| DELETE | /api/bills/{id} | Delete one bill |
| DELETE | /api/bills | Delete all bills |
| GET | /api/bills/export | Download as bill.txt |
| GET | /api/tariff | Current tariff slabs |

Change the tariff by editing `SLABS` and `FIXED_CHARGE` at the top of `main.py`.

## Run without a black window (Windows)
Double-click `Start App.vbs` (stop with `Stop App.bat`). `build_exe.bat` builds a standalone `.exe`.

## Put it online (open with a link)
1. **Database (free):** create a project at neon.tech, copy the connection string (starts with `postgresql://`).
2. **GitHub:** create a repository and upload all files in this folder (not `bills.db`).
3. **Render:** New > Web Service > connect the repository, then set
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Environment variables: `DATABASE_URL` = the Neon string, `PYTHON_VERSION` = `3.12.7`
   - Instance type: Free
4. Open the `https://....onrender.com` link Render gives you.

Online, each visitor (browser) sees only their own saved bills. The free Render service sleeps after
about 15 minutes of no use, so the first page load can take around a minute.
