# app1/management/commands/import_rules.py
from django.core.management.base import BaseCommand, CommandError
from app1.models import Interventions, MetricRule
import pandas as pd

OP_MAP = {
    '==': 'eq', '=':'eq', 'eq':'eq',
    '!=':'neq', 'neq':'neq',
    '>':'gt', 'gt':'gt',
    '>=':'gte','gte':'gte',
    '<':'lt', 'lt':'lt',
    '<=':'lte','lte':'lte',
    'in':'in', 'not in':'nin', 'nin':'nin',
    'contains':'contains', 'not contains':'ncontains',
    'true':'true','false':'false',
    'empty':'empty','not empty':'nempty',
}

class Command(BaseCommand):
    help = "Import intervention rules from an Excel mapping"

    def add_arguments(self, parser):
        parser.add_argument('xlsx_path', type=str)

    def handle(self, *args, **opts):
        path = opts['xlsx_path']
        try:
            df = pd.read_excel(path)
        except Exception as e:
            raise CommandError(f'Cannot read {path}: {e}')

        # expected columns (case-insensitive)
        cols = {c.lower(): c for c in df.columns}
        required = ['intervention','field','operator']
        for r in required:
            if r not in cols:
                raise CommandError(f'Missing column "{r}" in Excel.')

        created = 0
        for _, row in df.iterrows():
            name = str(row[cols['intervention']]).strip()
            field = str(row[cols['field']]).strip()
            op_raw = str(row[cols['operator']]).strip().lower()
            val = str(row[cols['value']]).strip() if 'value' in cols else ''

            op = OP_MAP.get(op_raw)
            if not op:
                self.stdout.write(self.style.WARNING(f'Skip "{name}": unknown operator "{op_raw}"'))
                continue

            iv = Interventions.objects.filter(name__iexact=name).first()
            if not iv:
                self.stdout.write(self.style.WARNING(f'Intervention not found: {name}'))
                continue

            MetricRule.objects.create(intervention=iv, field_name=field, operator=op, value=val or None)
            created += 1

        self.stdout.write(self.style.SUCCESS(f'Imported {created} rules.'))
