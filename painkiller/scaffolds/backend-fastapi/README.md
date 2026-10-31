# Backend

API do app em FastAPI. Guarda os segredos (chaves de serviços pagos) e fala com
os serviços externos; o app só conhece a URL dele (`VITE_API_URL`).

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest
```

Segredos chegam como variáveis de ambiente; veja `.env.example`.

Dados persistem só em `DATA_DIR` (SQLite em `app/db.py`); no deploy é `/data`,
um volume que sobrevive às publicações. Mudanças de esquema são sempre aditivas.
