import tempfile
import unittest
from pathlib import Path

from mailer import normalize_recipient, parse_vacancies


SAMPLE = """________________________________________________________________________
EMAIL VAGA 1
---------------
VAGA: Desenvolvedor Python
EMPRESA: Empresa A
EMAIL DO RECRUTADOR: recrutamento@empresa-a.com.br
LINK DA VAGA: https://example.com/1
ASSUNTO: Candidatura | Desenvolvedor Python

TEXTO DO EMAIL

Olá, equipe da Empresa A.
Tenho interesse na oportunidade.

________________________________________________________________________
EMAIL VAGA 2
---------------
VAGA: Analista Administrativo
EMPRESA: Empresa B
EMAIL DO RECRUTADOR: E-MAIL NÃO IDENTIFICADO - NÃO ENVIAR AUTOMATICAMENTE
LINK DA VAGA: https://example.com/2
ASSUNTO: Candidatura | Analista Administrativo

TEXTO DO EMAIL

Olá, equipe da Empresa B.
Tenho interesse na oportunidade.

________________________________________________________________________
"""


class MailerTests(unittest.TestCase):
    def test_parse_vacancies(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vagas.txt"
            path.write_text(SAMPLE, encoding="utf-8")
            vacancies = parse_vacancies(path)

        self.assertEqual(len(vacancies), 2)
        self.assertEqual(vacancies[0].number, 1)
        self.assertEqual(vacancies[0].recipient, "recrutamento@empresa-a.com.br")
        self.assertIn("Tenho interesse", vacancies[0].body)
        self.assertIsNone(vacancies[1].recipient)

    def test_normalize_recipient(self):
        self.assertEqual(
            normalize_recipient("RH <rh@empresa.com.br>"),
            "rh@empresa.com.br",
        )
        self.assertIsNone(normalize_recipient("E-mail não identificado"))
        self.assertIsNone(normalize_recipient("sem contato"))


if __name__ == "__main__":
    unittest.main()
