"""Utility for reading and extracting textual content from project attachments."""

import os
from typing import Optional


def extract_attachment_text(file_path: str) -> str:
    """Read attachment text safely from markdown, txt, docx, or pdf."""
    if not os.path.exists(file_path):
        return f"[Arquivo não encontrado: {file_path}]"

    ext = os.path.splitext(file_path)[1].lower()
    filename = os.path.basename(file_path)

    # 1. Plain text formats (.md, .txt, .json, code)
    if ext in [".md", ".txt", ".markdown", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css"]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return f"\n--- Conteúdo do Anexo ({filename}) ---\n{content}\n"
        except Exception as e:
            return f"[Erro ao ler {filename}: {e}]"

    # 2. PDF extraction
    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            pages = [page.extract_text() or "" for page in reader.pages]
            return f"\n--- Conteúdo do Anexo ({filename}) ---\n" + "\n".join(pages) + "\n"
        except ImportError:
            # Fallback if pypdf not installed: try basic byte stream text extract
            try:
                with open(file_path, "rb") as f:
                    raw = f.read().decode("latin-1", errors="ignore")
                return f"\n--- Conteúdo do Anexo ({filename}) [Modo Texto Bruto] ---\n{raw[:4000]}\n"
            except Exception:
                return f"[Anexo PDF {filename} anexado (pypdf não instalado para extração completa)]"
        except Exception as e:
            return f"[Erro ao ler PDF {filename}: {e}]"

    # 3. DOCX extraction
    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text]
            return f"\n--- Conteúdo do Anexo ({filename}) ---\n" + "\n".join(paragraphs) + "\n"
        except ImportError:
            return f"[Anexo DOCX {filename} registrado]"
        except Exception as e:
            return f"[Erro ao ler DOCX {filename}: {e}]"

    # Default fallback
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f"\n--- Conteúdo do Anexo ({filename}) ---\n" + f.read(5000) + "\n"
    except Exception:
        return f"[Anexo binário {filename} anexado]"
