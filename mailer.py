from __future__ import annotations

import argparse
import csv
import json
import os
import re
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Iterable

import certifi  # type: ignore[import-not-found]


EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
BLOCK_RE = re.compile(
    r"(?ms)^EMAIL\s+(?P<kind>VAGA|FREELA)\s+(?P<number>\d+)\s*\n-+\s*\n(?P<content>.*?)(?=^_{10,}\s*$|\Z)"
)


@dataclass(frozen=True)
class VacancyEmail:
    number: int
    vacancy: str
    company: str
    recipient: str | None
    link: str
    subject: str
    body: str


@dataclass(frozen=True)
class Settings:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    from_email: str
    from_name: str
    reply_to: str | None
    daily_limit: int
    interval_seconds: int


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs without adding a third-party dependency."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"Variável {name} precisa ser um inteiro, recebido: {raw!r}") from exc
    if value < 0:
        raise SystemExit(f"Variável {name} não pode ser negativa.")
    return value


def load_settings() -> Settings:
    required = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise SystemExit(
            "Configuração SMTP incompleta. Faltam: " + ", ".join(missing)
        )

    return Settings(
        smtp_host=os.environ["SMTP_HOST"].strip(),
        smtp_port=env_int("SMTP_PORT", 587),
        smtp_user=os.environ["SMTP_USER"].strip(),
        smtp_password=os.environ["SMTP_PASSWORD"],
        from_email=os.environ["SMTP_FROM_EMAIL"].strip(),
        from_name=os.getenv("SMTP_FROM_NAME", "Carlos Henrique Caldeira").strip(),
        reply_to=(os.getenv("SMTP_REPLY_TO", "").strip() or None),
        daily_limit=env_int("DAILY_LIMIT", 25),
        interval_seconds=env_int("SEND_INTERVAL_SECONDS", 120),
    )


def field(content: str, label: str) -> str:
    match = re.search(rf"(?mi)^{re.escape(label)}\s*:\s*(.*?)\s*$", content)
    return match.group(1).strip() if match else ""


def normalize_recipient(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None

    upper = value.upper()
    if "NÃO IDENTIFICADO" in upper or "NAO IDENTIFICADO" in upper:
        return None

    # Aceita eventual formato "Nome <email@dominio.com>" ou múltiplos dados na linha,
    # mas envia somente para o primeiro endereço sintaticamente válido.
    candidates = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.IGNORECASE)
    for candidate in candidates:
        if EMAIL_RE.fullmatch(candidate):
            return candidate
    return None


def parse_vacancies(path: Path) -> list[VacancyEmail]:
    text = path.read_text(encoding="utf-8-sig")
    vacancies: list[VacancyEmail] = []

    for match in BLOCK_RE.finditer(text):
        number = int(match.group("number"))
        content = match.group("content").strip()

        marker = re.search(r"(?mi)^TEXTO DO EMAIL\s*:?\s*$", content)
        if marker:
            body = content[marker.end():].strip()
            metadata = content[: marker.start()]
        else:
            body = ""
            metadata = content

        vacancies.append(
            VacancyEmail(
                number=number,
                vacancy=field(metadata, "VAGA") or field(metadata, "PROJETO/VAGA"),
                company=field(metadata, "EMPRESA") or field(metadata, "EMPRESA/CONTATO"),
                recipient=normalize_recipient(field(metadata, "EMAIL DO RECRUTADOR") or field(metadata, "EMAIL")),
                link=field(metadata, "LINK DA VAGA") or field(metadata, "FONTE"),
                subject=field(metadata, "ASSUNTO"),
                body=body,
            )
        )

    if not vacancies:
        raise ValueError(f"Nenhum bloco 'EMAIL VAGA N' encontrado em {path}")

    return vacancies


def build_message(vacancy: VacancyEmail, settings: Settings, cv_path: Path) -> EmailMessage:
    if not vacancy.recipient:
        raise ValueError("Vaga sem e-mail válido")
    if not vacancy.subject:
        raise ValueError(f"Vaga {vacancy.number} sem assunto")
    if not vacancy.body:
        raise ValueError(f"Vaga {vacancy.number} sem corpo de e-mail")

    msg = EmailMessage()
    msg["From"] = f"{settings.from_name} <{settings.from_email}>"
    msg["To"] = vacancy.recipient
    msg["Subject"] = vacancy.subject
    msg["Date"] = format_datetime(datetime.now().astimezone())
    msg["Message-ID"] = make_msgid(domain=settings.from_email.split("@")[-1])
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to

    msg.set_content(vacancy.body.strip() + "\n")

    cv_bytes = cv_path.read_bytes()
    msg.add_attachment(
        cv_bytes,
        maintype="application",
        subtype="pdf",
        filename=cv_path.name,
    )
    return msg


def open_smtp(settings: Settings) -> smtplib.SMTP:
    context = ssl.create_default_context(cafile=certifi.where())

    if settings.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            context=context,
            timeout=30,
        )
        smtp.ehlo()
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()

    smtp.login(settings.smtp_user, settings.smtp_password)
    return smtp


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"sent": {}, "history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Não foi possível ler o estado {path}: {exc}") from exc
    data.setdefault("sent", {})
    data.setdefault("history", [])
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def sent_last_24h(state: dict, sender: str) -> int:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    total = 0
    sender_key = sender.strip().lower()

    for item in state.get("history", []):
        if isinstance(item, dict):
            raw_timestamp = item.get("timestamp", "")
            item_sender = str(item.get("sender", "")).strip().lower()
        else:
            # Compatibilidade com os 100 envios feitos antes do histórico por conta.
            raw_timestamp = item
            item_sender = "crick.lucas@gmail.com"

        if item_sender != sender_key:
            continue
        try:
            ts = datetime.fromisoformat(str(raw_timestamp))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            total += 1
    return total


def wait_before_next(seconds: int, next_index: int, total: int) -> None:
    """Exibe uma contagem regressiva durante o intervalo entre envios."""
    for remaining in range(seconds, 0, -1):
        print(
            f"\rAguardando próximo envio: {remaining:3d}s | próximo [{next_index}/{total}]",
            end="",
            flush=True,
        )
        time.sleep(1)
    print("\r" + (" " * 80) + "\r", end="", flush=True)


def append_log(path: Path, vacancy: VacancyEmail, status: str, detail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow(
                ["timestamp", "vaga_numero", "vaga", "empresa", "destinatario", "status", "detalhe"]
            )
        writer.writerow(
            [
                datetime.now().astimezone().isoformat(timespec="seconds"),
                vacancy.number,
                vacancy.vacancy,
                vacancy.company,
                vacancy.recipient or "",
                status,
                detail,
            ]
        )


def select_vacancies(
    vacancies: Iterable[VacancyEmail],
    state: dict,
    start_at: int | None,
    only: int | None,
) -> list[VacancyEmail]:
    sent = {str(key) for key in state.get("sent", {}).keys()}
    selected: list[VacancyEmail] = []

    for vacancy in vacancies:
        if only is not None and vacancy.number != only:
            continue
        if start_at is not None and vacancy.number < start_at:
            continue
        if str(vacancy.number) in sent:
            continue
        selected.append(vacancy)

    return selected


def print_preview(vacancy: VacancyEmail, cv_path: Path) -> None:
    recipient = vacancy.recipient or "[SEM E-MAIL - SERÁ IGNORADA]"
    print("\n" + "=" * 78)
    print(f"VAGA {vacancy.number}: {vacancy.vacancy}")
    print(f"EMPRESA: {vacancy.company}")
    print(f"PARA: {recipient}")
    print(f"ASSUNTO: {vacancy.subject}")
    print(f"ANEXO: {cv_path}")
    print("-" * 78)
    print(vacancy.body[:1200])
    if len(vacancy.body) > 1200:
        print("...[prévia truncada]")


def run(args: argparse.Namespace) -> int:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / ".env")

    txt_path = Path(args.txt).expanduser().resolve()
    cv_path = Path(args.cv).expanduser().resolve()

    if not txt_path.is_file():
        raise SystemExit(f"TXT não encontrado: {txt_path}")
    if not cv_path.is_file():
        raise SystemExit(f"PDF do currículo não encontrado: {cv_path}")
    if cv_path.suffix.lower() != ".pdf":
        raise SystemExit("O currículo precisa ser um arquivo .pdf")

    source_text = txt_path.read_text(encoding="utf-8-sig")
    is_freela = bool(re.search(r"(?mi)^EMAIL\s+FREELA\s+\d+\s*$", source_text))
    default_state = base_dir / ("state_freelas.json" if is_freela else "state.json")
    default_log = base_dir / "logs" / ("envios_freelas.csv" if is_freela else "envios.csv")
    state_path = Path(args.state).expanduser().resolve() if args.state else default_state.resolve()
    log_path = Path(args.log).expanduser().resolve() if args.log else default_log.resolve()

    vacancies = parse_vacancies(txt_path)
    state = load_state(state_path)
    selected = select_vacancies(vacancies, state, args.start_at, args.only)

    invalid = [v for v in selected if not v.recipient]
    sendable = [v for v in selected if v.recipient]

    print(f"Blocos encontrados no TXT: {len(vacancies)}")
    print(f"Pendentes selecionados: {len(selected)}")
    print(f"Com destinatário válido: {len(sendable)}")
    print(f"Sem e-mail, serão ignorados: {len(invalid)}")

    for vacancy in invalid:
        append_log(log_path, vacancy, "SKIPPED_NO_EMAIL")

    if args.dry_run:
        preview_count = min(args.limit or 5, len(sendable))
        for vacancy in sendable[:preview_count]:
            print_preview(vacancy, cv_path)
        print("\nDRY-RUN concluído. Nenhum e-mail foi enviado.")
        return 0

    if not args.send:
        raise SystemExit("Para enviar de verdade, use --send. Para testar, use --dry-run.")

    settings = load_settings()
    already_today = sent_last_24h(state, settings.smtp_user)
    available_today = max(settings.daily_limit - already_today, 0)
    requested_limit = args.limit if args.limit is not None else len(sendable)
    run_limit = min(requested_limit, available_today, len(sendable))

    if run_limit <= 0:
        print(
            f"Limite das últimas 24h atingido ({already_today}/{settings.daily_limit}). "
            "Nada será enviado nesta execução."
        )
        return 0

    queue = sendable[:run_limit]
    print(
        f"Envio real: {len(queue)} mensagem(ns), intervalo de "
        f"{settings.interval_seconds}s, limite de 24h={settings.daily_limit}."
    )

    smtp: smtplib.SMTP | None = None
    try:
        smtp = open_smtp(settings)
        for index, vacancy in enumerate(queue, start=1):
            try:
                msg = build_message(vacancy, settings, cv_path)
                smtp.send_message(msg)

                timestamp = datetime.now(timezone.utc).isoformat()
                state["sent"][str(vacancy.number)] = {
                    "timestamp": timestamp,
                    "recipient": vacancy.recipient,
                    "subject": vacancy.subject,
                    "sender": settings.smtp_user,
                }
                state["history"].append(
                    {"timestamp": timestamp, "sender": settings.smtp_user}
                )
                save_state(state_path, state)
                append_log(log_path, vacancy, "SENT")

                print(
                    f"[{index}/{len(queue)}] ENVIADO | vaga {vacancy.number} | "
                    f"{vacancy.recipient}"
                )
            except Exception as exc:  # registra e continua para a próxima vaga
                append_log(log_path, vacancy, "ERROR", repr(exc))
                print(
                    f"[{index}/{len(queue)}] ERRO | vaga {vacancy.number} | {exc}",
                    file=sys.stderr,
                )

                # Reconecta caso o servidor tenha derrubado a sessão.
                try:
                    if smtp is not None:
                        smtp.quit()
                except Exception:
                    pass
                smtp = open_smtp(settings)

            if index < len(queue) and settings.interval_seconds:
                wait_before_next(settings.interval_seconds, index + 1, len(queue))
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                pass

    return 0


def build_parser() -> argparse.ArgumentParser:
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Envia candidaturas individualmente a partir do TXT do Nerdin."
    )
    parser.add_argument("--txt", default=str(base_dir / "data" / "vagas.txt"))
    parser.add_argument("--cv", default=str(base_dir / "data" / "curriculo.pdf"))
    parser.add_argument("--state", default=None, help="Estado customizado; padrão é separado por tipo de TXT")
    parser.add_argument("--log", default=None, help="Log customizado; padrão é separado por tipo de TXT")
    parser.add_argument("--limit", type=int, default=None, help="Máximo nesta execução")
    parser.add_argument("--start-at", type=int, default=None, help="Começa na vaga N")
    parser.add_argument("--only", type=int, default=None, help="Processa somente a vaga N")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Mostra prévia sem enviar")
    mode.add_argument("--send", action="store_true", help="Envia e-mails de verdade")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
