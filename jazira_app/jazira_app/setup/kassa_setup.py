# -*- coding: utf-8 -*-
# Copyright (c) 2026, Jazira App
# License: MIT

"""
Kassa Module Setup - Party Type'larni yaratish
===============================================

Ishlatish:
    bench --site [site] execute jazira_app.jazira_app.setup.kassa_setup.create_party_types
"""

import frappe


def create_party_types():
    """Kassa uchun yangi Party Type'lar yaratish."""
    party_types = [
        {"party_type": "Расходы", "account_type": "Payable"}
    ]
    
    for pt in party_types:
        try:
            if not frappe.db.exists("Party Type", pt["party_type"]):
                doc = frappe.new_doc("Party Type")
                doc.party_type = pt["party_type"]
                doc.account_type = pt["account_type"]
                doc.flags.ignore_links = True
                doc.insert(ignore_permissions=True)
                frappe.db.commit()
                print(f"✅ Created Party Type: {pt['party_type']}")
            else:
                print(f"⏭️  Party Type already exists: {pt['party_type']}")
        except Exception as e:
            print(f"⚠️  Error creating {pt['party_type']}: {str(e)}")
    
    print("\n✅ Party Types setup completed!")


def create_sample_filials():
    """Namuna filiallar yaratish."""
    filials = ["Административ", "База", "Filial 1"]
    
    for name in filials:
        try:
            if not frappe.db.exists("Kassa Filial", name):
                doc = frappe.new_doc("Kassa Filial")
                doc.filial_name = name
                doc.is_active = 1
                doc.insert(ignore_permissions=True)
                frappe.db.commit()
                print(f"✅ Created Kassa Filial: {name}")
            else:
                print(f"⏭️  Kassa Filial already exists: {name}")
        except Exception as e:
            print(f"⚠️  Error creating {name}: {str(e)}")


def run_full_setup():
    """To'liq setup."""
    print("=" * 50)
    print("KASSA MODULE SETUP")
    print("=" * 50)
    
    print("\n1. Creating Party Types...")
    create_party_types()
    
    print("\n2. Creating Sample Filials...")
    create_sample_filials()

    print("\n" + "=" * 50)
    print("✅ SETUP COMPLETED!")
    print("=" * 50)
