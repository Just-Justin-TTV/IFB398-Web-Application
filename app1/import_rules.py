from django.core.management.base import BaseCommand
from django.db import transaction
import pandas as pd
from app1.models import Interventions, MetricRule, InterventionConflict

class Command(BaseCommand):
    help = "Import metric rules and conflicts from the generated Excel."

    def add_arguments(self, parser):
        parser.add_argument("--path", required=True, help="C:\Users\nseth\Downloads\IFB398-Web-Application-2\app1\static\all_interventions_metric_mapping_v2.xlsx")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = opts["path"]
        # --- Raw (with rules) -> MetricRule ---
        raw = pd.read_excel(path, sheet_name="Raw (with rules)")
        raw = raw.fillna("")
        created_rules = 0

        for _, row in raw.iterrows():
            name = str(row.get("Name") or row.get("Intervention") or "").strip()
            if not name:
                continue
            iv = Interventions.objects.filter(name=name).first()
            if not iv:
                continue
            # parse stringified list of dicts -> very simple/naive eval
            rules_str = str(row.get("Rules") or "").strip()
            if not rules_str or rules_str == "[]":
                continue
            # safe-ish parse: expect pattern "[{'metric_key':..., 'operator':..., 'value':...}, ...]"
            try:
                import ast
                rules_list = ast.literal_eval(rules_str)
            except Exception:
                continue
            for r in rules_list:
                MetricRule.objects.get_or_create(
                    intervention=iv,
                    metric_key=r.get("metric_key"),
                    operator=r.get("operator"),
                    value=str(r.get("value")),
                )
                created_rules += 1

        # --- Conflicts sheet -> InterventionConflict ---
        try:
            cdf = pd.read_excel(path, sheet_name="Conflicts").fillna("")
        except Exception:
            cdf = pd.DataFrame()

        created_conflicts = 0
        for _, row in cdf.iterrows():
            a_name = str(row.get("A_Intervention","")).strip()
            b_name = str(row.get("B_Intervention","")).strip()
            ctype  = str(row.get("Type","")).strip() or "Conflict"
            reason = str(row.get("Reason","")).strip()

            if not a_name or not b_name:
                continue
            A = Interventions.objects.filter(name=a_name).first()
            B = Interventions.objects.filter(name=b_name).first()
            if not A or not B or A.id == B.id:
                continue
            # store pair in canonical A.id < B.id order
            a_obj, b_obj = (A,B) if A.id < B.id else (B,A)
            InterventionConflict.objects.get_or_create(
                A=a_obj, B=b_obj,
                defaults={"conflict_type": ctype, "reason": reason}
            )
            created_conflicts += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported {created_rules} rules and {created_conflicts} conflicts."
        ))
