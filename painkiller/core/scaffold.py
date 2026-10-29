"""Unpack a template's scaffold (.zip) into a new project's repository."""

import os
import shutil
import stat
import zipfile

#: Nunca vêm do zip: histórico de outro repositório, dependências instaladas e
#: lixo de sistema. O agente reinstala com o cache do projeto.
SKIPPED_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv", "__MACOSX", ".DS_Store", ".painkiller"}

#: Teto do conteúdo descompactado: um zip-bomba não pode encher o disco.
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class ScaffoldError(ValueError):
    pass


def _common_root(names: list[str]) -> str:
    """The single top-level folder every entry sits under (zips made by "compress folder"), or ''."""
    # O __MACOSX que o Finder acrescenta não conta como segunda raiz.
    names = [n for n in names if n.strip("/") and n.split("/", 1)[0] not in SKIPPED_PARTS]
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) != 1:
        return ""
    top = next(iter(tops))
    # Um único arquivo na raiz não é pasta a remover.
    return top + "/" if any(n.startswith(top + "/") for n in names) else ""


def extract_scaffold(zip_path: str, dest: str) -> list[str]:
    """Extract ``zip_path`` into ``dest`` and return the relative paths written.

    Arquivos do zip sobrescrevem os do repositório recém-criado (README,
    .gitignore): o arcabouço é a fonte da verdade. Entradas que escapariam de
    ``dest`` (``../``, caminho absoluto) são recusadas.
    """
    dest_real = os.path.realpath(dest)
    written: list[str] = []
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ScaffoldError(f"arcabouço inválido: {e}") from e

    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ScaffoldError("arcabouço grande demais")
        root = _common_root([i.filename.replace("\\", "/") for i in infos])

        for info in infos:
            name = info.filename.replace("\\", "/")
            if root and name.startswith(root):
                name = name[len(root):]
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if not parts or SKIPPED_PARTS.intersection(parts):
                continue
            target = os.path.realpath(os.path.join(dest_real, *parts))
            if ".." in parts or os.path.isabs(name) or not target.startswith(dest_real + os.sep):
                raise ScaffoldError(f"caminho inválido no arcabouço: {info.filename}")
            # Symlink no zip viraria link para fora do repositório: grava como arquivo comum.
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            mode = (info.external_attr >> 16) & 0o777
            if mode & stat.S_IXUSR:
                os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            written.append("/".join(parts))
    return written


def _walk_scaffold_dir(src: str):
    """Yield (absolute, relative posix) paths of the files of a scaffold folder."""
    for root, dirs, files in os.walk(src):
        # build/ e .gradle/ são saída de um build local do arcabouço embutido.
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_PARTS and d not in ("build", ".gradle", ".idea"))
        for name in sorted(files):
            if name in SKIPPED_PARTS or name == "local.properties":
                continue
            path = os.path.join(root, name)
            yield path, os.path.relpath(path, src).replace(os.sep, "/")


def copy_scaffold_dir(src: str, dest: str) -> list[str]:
    """Copy a scaffold folder (the bundled one) into ``dest``; same rules as the zip."""
    if not os.path.isdir(src):
        raise ScaffoldError(f"arcabouço não encontrado: {src}")
    written: list[str] = []
    for path, rel in _walk_scaffold_dir(src):
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
        # O checkout no Windows perde o bit de execução do gradlew.
        if rel == "gradlew" or (os.name != "nt" and os.access(path, os.X_OK)):
            os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(rel)
    return written


def zip_scaffold_dir(src: str, zip_path: str) -> str:
    """Pack a scaffold folder as a .zip, so the admin can download and adapt it."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, rel in _walk_scaffold_dir(src):
            info = zipfile.ZipInfo.from_file(path, rel)
            if rel == "gradlew":
                info.external_attr = (0o755 | stat.S_IFREG) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(path, "rb") as f:
                archive.writestr(info, f.read())
    return zip_path
