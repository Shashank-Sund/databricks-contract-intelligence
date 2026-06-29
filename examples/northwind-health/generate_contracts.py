"""
generate_contracts.py
======================
Writes 8 managed-care agreement PDFs + 2 amendment PDFs to
./contracts/.

Each main agreement is a full 8-10 page managed-care document with realistic
structure: cover/header, recitals, and numbered articles covering definitions,
scope, provider obligations & representations, covered services, utilization
management & medical necessity, credentialing & recredentialing, exclusions /
carve-outs, coordination of benefits, claims submission & adjudication (timely
filing), prior authorization, reimbursement methodology + a fee schedule TABLE of
contracted rates by DRG and CPT, member grievances & provider appeals,
confidentiality & HIPAA, indemnification & insurance, term/termination/renewal,
and general provisions, plus a signature block. ALL rates, dates, timely-filing
and appeal windows, prior-auth flags, and renewal dates are pulled from
demo_config so the PDFs match the contract_terms table and the claims exactly;
the added prose only surrounds the same numbers.

Runs on stock Python 3.9 (reportlab + PIL present system-wide). It deliberately
imports only demo_config (pure stdlib) and reportlab so it has no pandas/faker
dependency and runs in the system interpreter.
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer,
    Table, TableStyle,
)

import demo_config as cfg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "contracts")
os.makedirs(OUT, exist_ok=True)

NAVY = colors.HexColor("#1F3864")
LTBLUE = colors.HexColor("#D9E1F2")
GREY = colors.HexColor("#7F7F7F")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("CoverTitle", parent=ss["Title"], fontSize=22,
                          textColor=NAVY, spaceAfter=6, leading=26))
    ss.add(ParagraphStyle("CoverSub", parent=ss["Normal"], fontSize=12,
                          textColor=GREY, alignment=TA_CENTER, spaceAfter=2))
    ss.add(ParagraphStyle("Article", parent=ss["Heading2"], fontSize=12,
                          textColor=NAVY, spaceBefore=12, spaceAfter=4))
    ss.add(ParagraphStyle("Clause", parent=ss["Normal"], fontSize=9.5,
                          leading=13, alignment=TA_JUSTIFY, spaceAfter=4))
    ss.add(ParagraphStyle("ClauseNum", parent=ss["Normal"], fontSize=9.5,
                          leading=13, alignment=TA_JUSTIFY, spaceAfter=4,
                          leftIndent=18))
    ss.add(ParagraphStyle("Small", parent=ss["Normal"], fontSize=8,
                          textColor=GREY))
    ss.add(ParagraphStyle("TblHdr", parent=ss["Normal"], fontSize=8.5,
                          textColor=colors.white, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("TblCell", parent=ss["Normal"], fontSize=8.5, leading=10))
    return ss


SS = _styles()


def _fmt(d):
    return d.strftime("%B %d, %Y")


def _money(x):
    return f"${x:,.0f}"


class NumberedDoc(BaseDocTemplate):
    """Doc template that stamps a confidential footer + page number + payer name."""

    def __init__(self, filename, payer, contract_no, **kw):
        super().__init__(filename, pagesize=letter,
                         leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                         topMargin=1.0 * inch, bottomMargin=0.9 * inch, **kw)
        self.payer = payer
        self.contract_no = contract_no
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="main")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame],
                                            onPage=self._decorate)])

    def _decorate(self, canvas, doc):
        canvas.saveState()
        # top rule + running header
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(1.2)
        canvas.line(doc.leftMargin, letter[1] - 0.7 * inch,
                    letter[0] - doc.rightMargin, letter[1] - 0.7 * inch)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(doc.leftMargin, letter[1] - 0.62 * inch,
                          f"{cfg.HEALTH_SYSTEM}  -  Participating Provider Agreement")
        canvas.drawRightString(letter[0] - doc.rightMargin, letter[1] - 0.62 * inch,
                               f"Contract No. {self.contract_no}")
        # footer
        canvas.setStrokeColor(GREY)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 0.7 * inch,
                    letter[0] - doc.rightMargin, 0.7 * inch)
        canvas.drawString(doc.leftMargin, 0.55 * inch,
                          "CONFIDENTIAL - Synthetic demo document. Not a real contract.")
        canvas.drawRightString(letter[0] - doc.rightMargin, 0.55 * inch,
                               f"Page {doc.page}")
        canvas.restoreState()


def _clause(num, text):
    return Paragraph(f"<b>{num}</b>&nbsp;&nbsp;{text}", SS["ClauseNum"])


def _fee_schedule_table(payer):
    p = cfg.PAYERS[payer]
    # Build amendment override lookup
    rate_over = {(a["payer"], a["drg"]): a["new_rate_override"]
                 for a in cfg.AMENDMENTS if a["type"] == "rate_change"}

    head = [Paragraph(h, SS["TblHdr"]) for h in
            ["DRG", "Description", "Medicare Base", "Factor", "Contracted Case Rate"]]
    data = [head]
    for drg, d in cfg.DRGS.items():
        rate = cfg.contracted_rate(payer, drg)
        note = ""
        if (payer, drg) in rate_over:
            rate = rate_over[(payer, drg)]
            note = " *"
        factor = f"{int(p['factor']*100)}%" if p["method"].startswith("Percent") else "case rate"
        data.append([
            Paragraph(drg, SS["TblCell"]),
            Paragraph(d["desc"], SS["TblCell"]),
            Paragraph(_money(d["medicare"]), SS["TblCell"]),
            Paragraph(factor, SS["TblCell"]),
            Paragraph(_money(rate) + note, SS["TblCell"]),
        ])
    t = Table(data, colWidths=[0.55*inch, 2.7*inch, 1.0*inch, 0.75*inch, 1.35*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LTBLUE]),
        ("GRID", (0, 0), (-1, -1), 0.4, GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _cpt_table(payer):
    head = [Paragraph(h, SS["TblHdr"]) for h in
            ["CPT", "Procedure", "Contracted Rate", "Prior Auth"]]
    data = [head]
    for cpt, c in cfg.CPTS.items():
        rate = cfg.contracted_cpt_rate(payer, cpt)
        pa = "Yes" if (cpt in cfg.PRIOR_AUTH_CPTS and cfg.PAYERS[payer]["prior_auth_required"]) else "No"
        data.append([
            Paragraph(cpt, SS["TblCell"]),
            Paragraph(c["desc"], SS["TblCell"]),
            Paragraph(_money(rate), SS["TblCell"]),
            Paragraph(pa, SS["TblCell"]),
        ])
    t = Table(data, colWidths=[0.7*inch, 3.1*inch, 1.3*inch, 1.0*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LTBLUE]),
        ("GRID", (0, 0), (-1, -1), 0.4, GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _recital(text):
    return Paragraph(text, SS["Clause"])


def build_contract(payer, contract_no):
    p = cfg.PAYERS[payer]
    fname = os.path.join(OUT, f"{contract_no}_{payer.replace(' ', '_').replace('(', '').replace(')', '')}.pdf")
    doc = NumberedDoc(fname, payer, contract_no)
    fl = []

    pct = int(round(p["factor"] * 100))
    is_percent = p["method"].startswith("Percent")
    plan_type = p["plan_type"]

    # ---- cover ----
    fl.append(Spacer(1, 0.6 * inch))
    fl.append(Paragraph("PARTICIPATING PROVIDER AGREEMENT", SS["CoverTitle"]))
    fl.append(Paragraph("Managed Care Network Participation & Reimbursement", SS["CoverSub"]))
    fl.append(Spacer(1, 0.3 * inch))
    cover = [
        ["Payer / Plan:", payer],
        ["Plan Type:", plan_type],
        ["Provider Organization:", cfg.HEALTH_SYSTEM],
        ["Provider Tax ID:", cfg.HEALTH_SYSTEM_TIN],
        ["Contract Number:", contract_no],
        ["Reimbursement Methodology:", p["method"]],
        ["Effective Date:", _fmt(p["effective"])],
        ["Termination Date:", _fmt(p["term"])],
        ["Renewal / Notice Date:", _fmt(p["renewal"])],
    ]
    ct = Table(cover, colWidths=[2.2 * inch, 4.0 * inch])
    ct.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, LTBLUE),
    ]))
    fl.append(ct)
    fl.append(Spacer(1, 0.3 * inch))
    fl.append(Paragraph(
        f"This Participating Provider Agreement (the &ldquo;Agreement&rdquo;) is entered into by and between "
        f"<b>{payer}</b> (&ldquo;Payer&rdquo;) and <b>{cfg.HEALTH_SYSTEM}</b> (&ldquo;Provider&rdquo;), "
        f"effective as of {_fmt(p['effective'])}.", SS["Clause"]))
    fl.append(Spacer(1, 0.18 * inch))
    fl.append(Paragraph(
        "This cover page is a summary for administrative convenience only. In the event of any conflict "
        "between this cover page and the body of the Agreement, the body of the Agreement controls. "
        "The Exhibits, Appendices, and any duly executed Amendments are incorporated herein by reference.",
        SS["Small"]))
    fl.append(PageBreak())

    # ---- Recitals ----
    fl.append(Paragraph("RECITALS", SS["Article"]))
    fl.append(_recital(
        f"WHEREAS, {payer} (&ldquo;Payer&rdquo;) arranges for the provision of health care services to "
        f"individuals enrolled in one or more {plan_type} benefit plans for which Payer provides or "
        f"administers coverage (each, a &ldquo;Member&rdquo;); and"))
    fl.append(_recital(
        f"WHEREAS, {cfg.HEALTH_SYSTEM} (&ldquo;Provider&rdquo;) is a duly licensed health system operating "
        f"the hospitals, ambulatory facilities, and professional practices identified in Appendix 1, and "
        f"holds federal Tax Identification Number {cfg.HEALTH_SYSTEM_TIN}; and"))
    fl.append(_recital(
        "WHEREAS, Provider desires to participate in Payer&rsquo;s provider network and to render Covered "
        "Services to Members, and Payer desires to include Provider in its network on the terms set forth "
        "herein; and"))
    fl.append(_recital(
        "WHEREAS, the parties intend that this Agreement comply with all applicable federal and state laws "
        "governing the delivery and reimbursement of health care services, including the privacy and "
        "security standards of the Health Insurance Portability and Accountability Act of 1996 (HIPAA);"))
    fl.append(_recital(
        "NOW, THEREFORE, in consideration of the mutual covenants and promises set forth herein, and other "
        "good and valuable consideration, the receipt and sufficiency of which are hereby acknowledged, the "
        "parties agree as follows:"))

    # ---- Article 1 Definitions ----
    fl.append(Paragraph("ARTICLE 1. DEFINITIONS", SS["Article"]))
    fl.append(_recital("As used in this Agreement, the following capitalized terms shall have the meanings "
              "set forth below. Terms not defined herein shall have the meaning ascribed to them under "
              "applicable law or, where applicable, the relevant Plan documents."))
    fl.append(_clause("1.1", "&ldquo;Clean Claim&rdquo; means a claim submitted on the applicable "
              "CMS-1450 (UB-04) or CMS-1500 form, or its electronic 837 equivalent, that requires no "
              "further information, documentation, or substantiation in order to be adjudicated and that is "
              "not subject to a pending investigation of fraud or abuse."))
    fl.append(_clause("1.2", "&ldquo;Covered Services&rdquo; means those medically necessary health care "
              "services and supplies that are benefits under the applicable Plan and that are rendered to a "
              "Member by Provider during the term of this Agreement."))
    fl.append(_clause("1.3", "&ldquo;Contracted Rate&rdquo; means the amount payable to Provider for a "
              "Covered Service as set forth in the Fee Schedule in Article 11 and Exhibits A and B, as the "
              "same may be amended from time to time in accordance with Article 18."))
    fl.append(_clause("1.4", "&ldquo;Medical Necessity&rdquo; or &ldquo;Medically Necessary&rdquo; means "
              "health care services that a prudent physician would provide for the purpose of preventing, "
              "evaluating, diagnosing, or treating an illness, injury, or disease, consistent with generally "
              "accepted standards of medical practice and not primarily for the convenience of the Member or "
              "Provider."))
    fl.append(_clause("1.5", "&ldquo;Member&rdquo; means an individual who is enrolled in and eligible for "
              "benefits under a Plan administered or insured by Payer on the date a Covered Service is "
              "rendered."))
    fl.append(_clause("1.6", "&ldquo;Plan&rdquo; means a health benefit plan offered, insured, or "
              f"administered by Payer under the {plan_type} product line to which this Agreement applies."))
    fl.append(_clause("1.7", "&ldquo;Remittance Advice&rdquo; means the electronic (835) or paper "
              "explanation of payment that accompanies or follows Payer&rsquo;s adjudication of a claim and "
              "states the allowed amount, payment, Member liability, and any adjustment or denial reason "
              "codes (CARC/RARC)."))
    fl.append(_clause("1.8", "&ldquo;Utilization Management&rdquo; means the prospective, concurrent, and "
              "retrospective review of the medical necessity, appropriateness, and efficiency of Covered "
              "Services, including prior authorization and concurrent review."))

    # ---- Article 2 Scope of Agreement ----
    fl.append(Paragraph("ARTICLE 2. SCOPE OF AGREEMENT", SS["Article"]))
    fl.append(_clause("2.1", f"This Agreement governs Provider&rsquo;s participation in Payer&rsquo;s "
              f"{plan_type} network and the reimbursement of Covered Services rendered to Members. It "
              "applies to all facilities and professional practices listed in Appendix 1 unless a specific "
              "facility is expressly excluded by a duly executed Amendment."))
    fl.append(_clause("2.2", "The parties intend that this Agreement be construed as a participating "
              "provider agreement and not as a partnership, joint venture, or employment relationship. Each "
              "party is an independent contractor and neither party shall have authority to bind the other "
              "except as expressly provided herein."))
    fl.append(_clause("2.3", "Provider&rsquo;s exercise of independent medical judgment with respect to the "
              "care of any Member shall not be governed or restricted by this Agreement. Nothing herein "
              "shall require Provider to render services that Provider determines are not medically "
              "appropriate, nor shall any reimbursement provision be construed as an inducement to limit "
              "Medically Necessary care."))

    # ---- Article 3 Provider Obligations & Representations ----
    fl.append(Paragraph("ARTICLE 3. PROVIDER OBLIGATIONS AND REPRESENTATIONS", SS["Article"]))
    fl.append(_clause("3.1", "Provider represents and warrants that it and each of its employed and "
              "contracted practitioners hold and shall maintain in good standing all licenses, "
              "certifications, registrations, and hospital privileges required to render Covered Services in "
              "the jurisdiction in which such services are provided."))
    fl.append(_clause("3.2", "Provider shall render Covered Services to Members in the same manner, in "
              "accordance with the same standards, and within the same time availability as offered to "
              "Provider&rsquo;s other patients, and shall not discriminate against any Member on the basis "
              "of source of payment, health status, or any protected classification."))
    fl.append(_clause("3.3", "Provider shall maintain accurate and complete medical, financial, and "
              "administrative records relating to Covered Services for a period of not less than ten (10) "
              "years, and shall make such records available to Payer and to regulatory authorities as "
              "permitted by law and Article 14 (Confidentiality)."))
    fl.append(_clause("3.4", "Provider represents that neither it nor any of its practitioners is excluded, "
              "debarred, or suspended from participation in any federal or state health care program, and "
              "Provider shall promptly notify Payer in writing of any event that would render this "
              "representation untrue."))
    fl.append(_clause("3.5", "Provider shall cooperate with Payer&rsquo;s quality improvement, peer review, "
              "and member-satisfaction programs and shall furnish encounter and clinical data reasonably "
              "necessary for Payer to meet its accreditation and regulatory reporting obligations."))
    fl.append(PageBreak())

    # ---- Article 4 Covered Services ----
    fl.append(Paragraph("ARTICLE 4. COVERED SERVICES", SS["Article"]))
    fl.append(_clause("4.1", "Provider shall furnish to Members those Covered Services that fall within "
              "Provider&rsquo;s scope of licensure and the categories of service for which Provider is "
              "credentialed under Article 6. Covered Services include inpatient hospital services, "
              "outpatient and ambulatory services, emergency services, and the professional services of "
              "Provider&rsquo;s practitioners."))
    fl.append(_clause("4.2", "Emergency services shall be rendered to any Member presenting with an "
              "emergency medical condition without regard to prior authorization, consistent with the "
              "prudent-layperson standard and applicable law. Payer shall reimburse Medically Necessary "
              "emergency services in accordance with Article 11."))
    fl.append(_clause("4.3", f"Services that are excluded from coverage, carved out to a separate vendor, "
              f"or otherwise not benefits under the applicable Plan are addressed in Article 7. For this "
              f"Plan, the following carve-out provision applies: {p['carve_outs']}"))

    # ---- Article 5 Utilization Management & Medical Necessity ----
    fl.append(Paragraph("ARTICLE 5. UTILIZATION MANAGEMENT AND MEDICAL NECESSITY", SS["Article"]))
    fl.append(_clause("5.1", "Payer shall maintain a Utilization Management program that applies "
              "objective, clinically based criteria consistent with generally accepted standards of medical "
              "practice. Payer shall make its UM criteria available to Provider upon request."))
    fl.append(_clause("5.2", "Coverage determinations that a service is not Medically Necessary shall be "
              "made by appropriately licensed clinical personnel, and any adverse determination shall be "
              "rendered by a physician or other qualified health professional with expertise in the "
              "applicable clinical area. Provider shall have the right to a peer-to-peer discussion prior to "
              "the issuance of an adverse determination where reasonably practicable."))
    fl.append(_clause("5.3", "Concurrent review of inpatient admissions shall be conducted in a manner that "
              "does not unreasonably interfere with the rendering of Medically Necessary care. Payer shall "
              "not retroactively deny an authorized service except in cases of fraud, material "
              "misrepresentation, or ineligibility of the Member on the date of service."))

    # ---- Article 6 Credentialing & Recredentialing ----
    fl.append(Paragraph("ARTICLE 6. CREDENTIALING AND RECREDENTIALING", SS["Article"]))
    fl.append(_clause("6.1", "Provider and each of its practitioners shall complete Payer&rsquo;s "
              "credentialing process prior to rendering Covered Services for which network participation is "
              "claimed, and shall be recredentialed not less frequently than once every thirty-six (36) "
              "months in accordance with applicable accreditation standards."))
    fl.append(_clause("6.2", "Provider shall submit complete and accurate credentialing applications, "
              "including evidence of licensure, board certification, malpractice history, and the insurance "
              "coverage required under Article 15. Provider shall notify Payer within five (5) business days "
              "of any material change in the credentialing status of any practitioner."))
    fl.append(_clause("6.3", "Payer may suspend or terminate the network participation of any individual "
              "practitioner who fails to satisfy credentialing requirements, without thereby terminating "
              "this Agreement as to Provider&rsquo;s remaining practitioners and facilities."))

    # ---- Article 7 Exclusions / carve-outs ----
    fl.append(Paragraph("ARTICLE 7. EXCLUSIONS AND CARVE-OUTS", SS["Article"]))
    fl.append(_clause("7.1", f"Carve-outs applicable to this Plan: {p['carve_outs']}"))
    fl.append(_clause("7.2", "Experimental, investigational, and cosmetic services are excluded from "
              "coverage and shall not be reimbursed under this Agreement, except where coverage is required "
              "by applicable law or an approved clinical trial determination."))
    fl.append(_clause("7.3", "Services rendered to an individual who is not an eligible Member on the date "
              "of service, and services that are the financial responsibility of another payer as primary, "
              "are excluded from reimbursement under this Agreement and are addressed in Article 8 "
              "(Coordination of Benefits)."))
    fl.append(PageBreak())

    # ---- Article 8 Coordination of Benefits ----
    fl.append(Paragraph("ARTICLE 8. COORDINATION OF BENEFITS", SS["Article"]))
    fl.append(_clause("8.1", "Where a Member is covered by more than one health benefit plan, benefits "
              "shall be coordinated in accordance with applicable law and the order-of-benefit-determination "
              "rules of the National Association of Insurance Commissioners, as adopted by the governing "
              "jurisdiction."))
    fl.append(_clause("8.2", "When Payer is the secondary plan, Payer&rsquo;s liability shall not exceed "
              "the amount that, when combined with the primary plan&rsquo;s payment, equals the Contracted "
              "Rate for the Covered Service. Provider shall pursue primary coverage in good faith and shall "
              "furnish primary remittance information with any secondary claim."))
    fl.append(_clause("8.3", "Provider shall identify and bill any liable third party (including workers&rsquo; "
              "compensation, automobile, and liability carriers) as primary where applicable, and shall "
              "cooperate with Payer&rsquo;s subrogation and recovery activities."))

    # ---- Article 9 Claims submission / timely filing ----
    fl.append(Paragraph("ARTICLE 9. CLAIMS SUBMISSION AND ADJUDICATION", SS["Article"]))
    fl.append(_clause("9.1", f"Provider shall submit all claims for Covered Services within "
              f"<b>{p['timely_filing_days']} calendar days</b> of the date of service (or, for inpatient "
              f"admissions, the date of discharge). Claims received after this {p['timely_filing_days']}-day "
              f"period may be denied for untimely filing, reported on the Remittance Advice as Claim "
              f"Adjustment Reason Code (CARC) 29."))
    fl.append(_clause("9.2", "Provider shall submit claims electronically in the ANSI X12 837 format "
              "through Payer&rsquo;s designated clearinghouse, using current and valid CPT, HCPCS, ICD-10, "
              "revenue, and MS-DRG codes. Paper claims shall be accepted only where electronic submission is "
              "not feasible."))
    fl.append(_clause("9.3", "Payer shall adjudicate and remit payment on each Clean Claim within thirty "
              "(30) calendar days of receipt via electronic remittance advice (835) and electronic funds "
              "transfer (EFT). Interest shall accrue on Clean Claims not paid within the statutory prompt-pay "
              "period at the rate required by applicable law."))
    fl.append(_clause("9.4", "Where a claim cannot be adjudicated as a Clean Claim, Payer shall request any "
              "additional information in writing within fifteen (15) business days of receipt, and Provider "
              "shall respond within a reasonable period. A claim that is denied solely for a curable defect "
              "may be corrected and resubmitted within the timely-filing window or thirty (30) days of the "
              "denial, whichever is later."))
    fl.append(_clause("9.5", "Payer may recover overpayments by offset against future payments or by "
              "written demand, provided that Payer furnishes Provider with an itemized explanation and a "
              "reasonable opportunity to contest the recovery before any offset is taken. Recovery of "
              "overpayments is subject to the lookback limitations of applicable law."))

    # ---- Article 10 Prior authorization ----
    fl.append(Paragraph("ARTICLE 10. PRIOR AUTHORIZATION", SS["Article"]))
    if p["prior_auth_required"]:
        fl.append(_clause("10.1", "Prior authorization is required for elective inpatient admissions, "
                  "advanced imaging (CT, MRI, PET), and the procedures designated in Exhibit B as requiring "
                  "prior authorization. Covered Services rendered without a required authorization may be "
                  "denied, reported on the Remittance Advice as CARC 197 (precertification/authorization "
                  "absent)."))
        fl.append(_clause("10.2", "Provider shall obtain prior authorization in advance of the scheduled "
                  "service, except for urgent or emergency services, for which authorization (where "
                  "required) may be obtained within forty-eight (48) hours after the service is initiated. "
                  "An approved authorization is a determination of Medical Necessity only and does not "
                  "guarantee Member eligibility or payment."))
        fl.append(_clause("10.3", f"Plan-specific authorization and vendor arrangements: {p['carve_outs']}"))
    else:
        fl.append(_clause("10.1", "Prior authorization is <b>not</b> required for in-network Covered "
                  "Services under this Plan, except for transplant services, clinical trials, and services "
                  "that the parties expressly designate in a duly executed Amendment."))
        fl.append(_clause("10.2", "Where prior authorization is not required, Payer retains the right to "
                  "conduct retrospective review of Medical Necessity in accordance with Article 5, subject "
                  "to the limitation on retroactive denial of authorized services set forth in Section 5.3."))
        fl.append(_clause("10.3", f"Plan-specific arrangements: {p['carve_outs']}"))
    fl.append(PageBreak())

    # ---- Article 11 Reimbursement methodology + fee schedules ----
    fl.append(Paragraph("ARTICLE 11. REIMBURSEMENT METHODOLOGY", SS["Article"]))
    if is_percent:
        fl.append(_clause("11.1", f"Inpatient Covered Services shall be reimbursed at "
                  f"<b>{pct}% of the then-current Medicare base payment</b> for the applicable MS-DRG, as "
                  f"set forth in Exhibit A (Inpatient DRG Fee Schedule)."))
    else:
        fl.append(_clause("11.1", "Inpatient Covered Services shall be reimbursed at the fixed "
                  "<b>per-DRG case rate</b> set forth in Exhibit A (Inpatient DRG Fee Schedule), inclusive "
                  "of all facility services for the admission."))
    fl.append(_clause("11.2", "Outpatient Covered Services shall be reimbursed per the contracted fee "
              "schedule in Exhibit B (Outpatient Procedure Fee Schedule). Where no fee schedule rate exists "
              "for a Covered Service, payment shall be the lesser of billed charges or the applicable "
              "Medicare allowable."))
    fl.append(_clause("11.3", "Payer shall pay the Contracted Rate less applicable Member cost-sharing "
              "(deductible, coinsurance, and copayment). The difference between billed charges and the "
              "Contracted Rate constitutes a contractual adjustment that Provider shall not bill to the "
              "Member (balance billing prohibited), except for applicable Member cost-sharing and "
              "non-covered services for which the Member has given informed written consent."))
    fl.append(_clause("11.4", "The rates set forth in the Exhibits are confidential and proprietary, are "
              "fixed for the term unless modified by a duly executed Amendment under Article 18, and "
              "supersede any conflicting fee schedule previously in effect between the parties."))

    fl.append(Paragraph("EXHIBIT A - INPATIENT DRG FEE SCHEDULE", SS["Article"]))
    fl.append(Paragraph("The following contracted case rates apply to inpatient admissions during the term:", SS["Clause"]))
    fl.append(Spacer(1, 0.06 * inch))
    fl.append(_fee_schedule_table(payer))
    rate_over_for_payer = [a for a in cfg.AMENDMENTS if a["type"] == "rate_change" and a["payer"] == payer]
    if rate_over_for_payer:
        fl.append(Spacer(1, 0.05 * inch))
        fl.append(Paragraph("* Rate revised by amendment; see Amendment "
                  f"{rate_over_for_payer[0]['amendment_no']}.", SS["Small"]))
    fl.append(Spacer(1, 0.18 * inch))
    fl.append(Paragraph("EXHIBIT B - OUTPATIENT PROCEDURE FEE SCHEDULE", SS["Article"]))
    fl.append(_cpt_table(payer))
    fl.append(PageBreak())

    # ---- Article 12 Member Grievances & Appeals ----
    fl.append(Paragraph("ARTICLE 12. MEMBER GRIEVANCES AND PROVIDER APPEALS", SS["Article"]))
    fl.append(_clause("12.1", f"Provider may appeal a claim determination within <b>{p['appeal_window_days']} "
              f"calendar days</b> of the Remittance Advice date. Appeals shall be submitted in writing with "
              f"supporting clinical and billing documentation and shall identify the claim, the disputed "
              f"determination, and the basis for the appeal."))
    fl.append(_clause("12.2", f"Payer shall acknowledge a provider appeal within fifteen (15) business days "
              f"and shall render a written determination within thirty (30) calendar days of receipt of a "
              f"complete appeal. The {p['appeal_window_days']}-day filing period applies to first-level "
              f"appeals; subsequent levels, if any, shall follow Payer&rsquo;s published appeals policy and "
              f"applicable law."))
    fl.append(_clause("12.3", "Provider shall cooperate with Payer in the resolution of Member grievances "
              "relating to Covered Services rendered by Provider, including furnishing relevant medical "
              "records and responding to inquiries within the timeframes required by applicable law and "
              "accreditation standards."))
    fl.append(_clause("12.4", "Nothing in this Article shall limit a Member&rsquo;s independent right to "
              "appeal an adverse benefit determination, to request external review, or to pursue any other "
              "remedy available under the Plan or applicable law."))

    # ---- Article 13 Coordination is above; Article 13 Confidentiality & HIPAA ----
    fl.append(Paragraph("ARTICLE 13. CONFIDENTIALITY AND HIPAA COMPLIANCE", SS["Article"]))
    fl.append(_clause("13.1", "Each party shall hold in confidence the other party&rsquo;s proprietary and "
              "confidential information, including the rates and Exhibits to this Agreement, and shall not "
              "disclose such information except as required by law, regulatory authority, or as reasonably "
              "necessary to perform its obligations hereunder."))
    fl.append(_clause("13.2", "Each party shall comply with the privacy, security, and breach-notification "
              "standards of the Health Insurance Portability and Accountability Act of 1996 (HIPAA), the "
              "Health Information Technology for Economic and Clinical Health (HITECH) Act, and their "
              "implementing regulations, with respect to all Protected Health Information exchanged under "
              "this Agreement."))
    fl.append(_clause("13.3", "The parties shall execute and maintain a Business Associate Agreement where "
              "required, and shall implement reasonable administrative, physical, and technical safeguards "
              "to protect Protected Health Information. Each party shall report any breach of unsecured "
              "Protected Health Information to the other party without unreasonable delay and consistent "
              "with applicable law."))

    # ---- Article 14 Indemnification & Insurance ----
    fl.append(Paragraph("ARTICLE 14. INDEMNIFICATION AND INSURANCE", SS["Article"]))
    fl.append(_clause("14.1", "Each party (the &ldquo;Indemnifying Party&rdquo;) shall indemnify, defend, "
              "and hold harmless the other party and its officers, directors, and employees from and against "
              "any third-party claims, damages, and reasonable expenses to the extent arising out of the "
              "Indemnifying Party&rsquo;s negligence, willful misconduct, or breach of this Agreement."))
    fl.append(_clause("14.2", "Provider shall maintain, at its sole expense, professional liability "
              "(medical malpractice) insurance with limits of not less than $1,000,000 per occurrence and "
              "$3,000,000 in the aggregate, and commercial general liability insurance in commercially "
              "reasonable amounts, with carriers authorized to do business in the applicable jurisdiction."))
    fl.append(_clause("14.3", "Each party shall furnish certificates of insurance upon request and shall "
              "provide the other party with not less than thirty (30) days&rsquo; prior written notice of "
              "any cancellation or material reduction in coverage. Self-insurance programs that meet "
              "applicable regulatory requirements satisfy this Article."))
    fl.append(PageBreak())

    # ---- Article 15 Term & renewal ----
    fl.append(Paragraph("ARTICLE 15. TERM, TERMINATION AND RENEWAL", SS["Article"]))
    fl.append(_clause("15.1", f"This Agreement is effective {_fmt(p['effective'])} and continues in full "
              f"force and effect through {_fmt(p['term'])} (the &ldquo;Initial Term&rdquo;)."))
    fl.append(_clause("15.2", f"Upon expiration of the Initial Term, this Agreement renews automatically "
              f"for successive twelve (12) month renewal terms unless either party provides written notice "
              f"of non-renewal to the other party on or before {_fmt(p['renewal'])}."))
    fl.append(_clause("15.3", "Either party may terminate this Agreement for cause upon sixty (60) days "
              "prior written notice specifying the alleged breach, provided that the breaching party shall "
              "have an opportunity to cure the breach within such sixty (60) day period. Termination shall "
              "be effective at the end of the cure period if the breach is not cured."))
    fl.append(_clause("15.4", "Either party may terminate this Agreement without cause upon ninety (90) "
              "days prior written notice. Payer may terminate immediately upon Provider&rsquo;s loss of "
              "licensure, exclusion from a federal or state health care program, or any event that "
              "materially impairs Provider&rsquo;s ability to render Covered Services safely."))
    fl.append(_clause("15.5", "Upon termination, Provider shall continue to render Covered Services to any "
              "Member then in an active course of treatment for a transitional period required by applicable "
              "law, at the Contracted Rate, to ensure continuity of care. The confidentiality, "
              "indemnification, and records-retention obligations survive termination."))

    # ---- Article 16 General Provisions ----
    fl.append(Paragraph("ARTICLE 16. GENERAL PROVISIONS", SS["Article"]))
    fl.append(_clause("16.1", "<b>Governing Law.</b> This Agreement shall be governed by and construed in "
              "accordance with the laws of the state in which Provider&rsquo;s principal facility is located, "
              "without regard to its conflict-of-laws principles, and subject to applicable federal law."))
    fl.append(_clause("16.2", "<b>Notices.</b> All notices required or permitted under this Agreement shall "
              "be in writing and shall be deemed given when delivered personally, sent by nationally "
              "recognized overnight courier, or sent by certified mail, return receipt requested, to the "
              "addresses set forth in Appendix 1 or as otherwise designated in writing by a party."))
    fl.append(_clause("16.3", "<b>Assignment.</b> Neither party may assign this Agreement, in whole or in "
              "part, without the prior written consent of the other party, except that either party may "
              "assign to an affiliate or successor in connection with a merger or sale of substantially all "
              "of its assets, upon written notice to the other party."))
    fl.append(_clause("16.4", "<b>Amendment.</b> Except as otherwise expressly provided herein, this "
              "Agreement may be amended only by a written instrument signed by authorized representatives of "
              "both parties. Amendments to the Exhibits and Fee Schedules are governed by Article 18 of any "
              "applicable Amendment and take effect on the stated effective date."))
    fl.append(_clause("16.5", "<b>Force Majeure.</b> Neither party shall be liable for any failure or delay "
              "in performance to the extent caused by events beyond its reasonable control, including acts of "
              "God, natural disaster, public health emergency, war, terrorism, labor disturbance, or failure "
              "of utilities or communications, provided that the affected party uses reasonable efforts to "
              "resume performance."))
    fl.append(_clause("16.6", "<b>Entire Agreement.</b> This Agreement, together with its Exhibits, "
              "Appendices, and duly executed Amendments, constitutes the entire agreement between the parties "
              "with respect to its subject matter and supersedes all prior understandings, whether oral or "
              "written."))
    fl.append(_clause("16.7", "<b>Severability.</b> If any provision of this Agreement is held to be "
              "invalid or unenforceable, the remaining provisions shall continue in full force and effect, "
              "and the parties shall negotiate in good faith a valid provision that most nearly effects the "
              "original intent."))
    fl.append(_clause("16.8", "<b>Waiver; Counterparts.</b> No waiver of any provision shall be effective "
              "unless in writing, and no waiver shall constitute a continuing waiver. This Agreement may be "
              "executed in counterparts, including by electronic signature, each of which shall be deemed an "
              "original and all of which together constitute one instrument."))

    # ---- signature ----
    fl.append(Spacer(1, 0.25 * inch))
    fl.append(Paragraph(
        "IN WITNESS WHEREOF, the parties have caused this Agreement to be executed by their duly authorized "
        "representatives as of the Effective Date first written above.", SS["Clause"]))
    fl.append(Spacer(1, 0.15 * inch))
    sig = [
        ["PAYER:", "", "PROVIDER:"],
        [payer, "", cfg.HEALTH_SYSTEM],
        ["By: ______________________", "", "By: ______________________"],
        ["Name: VP, Network Management", "", "Name: SVP, Revenue Cycle"],
        ["Title: Vice President", "", "Title: Senior Vice President"],
        [f"Date: {_fmt(p['effective'])}", "", f"Date: {_fmt(p['effective'])}"],
    ]
    st = Table(sig, colWidths=[2.6 * inch, 0.6 * inch, 2.6 * inch])
    st.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
                            ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
                            ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    fl.append(st)

    doc.build(fl)
    return fname


def build_amendment(am, contract_no):
    payer = am["payer"]
    p = cfg.PAYERS[payer]
    safe = payer.replace(' ', '_').replace('(', '').replace(')', '')
    fname = os.path.join(OUT, f"AMENDMENT_{am['amendment_no']}_{safe}.pdf")
    doc = NumberedDoc(fname, payer, contract_no)
    fl = []
    fl.append(Spacer(1, 0.5 * inch))
    fl.append(Paragraph(f"AMENDMENT {am['amendment_no']}", SS["CoverTitle"]))
    fl.append(Paragraph(f"to the Participating Provider Agreement with {payer}", SS["CoverSub"]))
    fl.append(Spacer(1, 0.25 * inch))
    meta = [
        ["Payer / Plan:", payer],
        ["Underlying Contract No.:", contract_no],
        ["Amendment No.:", am["amendment_no"]],
        ["Amendment Effective Date:", _fmt(am["effective"])],
        ["Provider Organization:", cfg.HEALTH_SYSTEM],
    ]
    mt = Table(meta, colWidths=[2.3 * inch, 4.0 * inch])
    mt.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                            ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
                            ("FONTSIZE", (0, 0), (-1, -1), 10),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.3, LTBLUE)]))
    fl.append(mt)
    fl.append(Spacer(1, 0.25 * inch))
    fl.append(Paragraph(
        f"This Amendment {am['amendment_no']} (the &ldquo;Amendment&rdquo;) is made effective "
        f"{_fmt(am['effective'])} and amends the Participating Provider Agreement between {payer} and "
        f"{cfg.HEALTH_SYSTEM}. Except as expressly modified below, all terms of the Agreement remain in "
        f"full force and effect.", SS["Clause"]))
    fl.append(Spacer(1, 0.1 * inch))

    if am["type"] == "rate_change":
        old_rate = cfg.contracted_rate(payer, am["drg"])
        fl.append(Paragraph("1. AMENDED FEE SCHEDULE", SS["Article"]))
        fl.append(_clause("1.1", am["summary"]))
        chg = [
            [Paragraph(h, SS["TblHdr"]) for h in
             ["DRG", "Description", "Prior Rate", "Amended Rate", "Effective"]],
            [Paragraph(am["drg"], SS["TblCell"]),
             Paragraph(cfg.DRGS[am["drg"]]["desc"], SS["TblCell"]),
             Paragraph(_money(old_rate), SS["TblCell"]),
             Paragraph(_money(am["new_rate_override"]), SS["TblCell"]),
             Paragraph(_fmt(am["effective"]), SS["TblCell"])],
        ]
        t = Table(chg, colWidths=[0.6*inch, 2.6*inch, 1.1*inch, 1.1*inch, 1.2*inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                               ("GRID", (0, 0), (-1, -1), 0.4, GREY),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        fl.append(Spacer(1, 0.06 * inch))
        fl.append(t)
        fl.append(Spacer(1, 0.1 * inch))
        fl.append(_clause("1.2", f"The amended rate represents an increase from {_money(old_rate)} "
                  f"to {_money(am['new_rate_override'])} and applies to admissions with a discharge date "
                  f"on or after {_fmt(am['effective'])}."))
    else:  # timely_filing_change
        fl.append(Paragraph("1. AMENDED TIMELY FILING WINDOW", SS["Article"]))
        fl.append(_clause("1.1", am["summary"]))
        chg = [
            [Paragraph(h, SS["TblHdr"]) for h in
             ["Provision", "Prior Term", "Amended Term", "Effective"]],
            [Paragraph("Timely filing window", SS["TblCell"]),
             Paragraph(f"{am['old_timely_filing_days']} days", SS["TblCell"]),
             Paragraph(f"{am['new_timely_filing_days']} days", SS["TblCell"]),
             Paragraph(_fmt(am["effective"]), SS["TblCell"])],
        ]
        t = Table(chg, colWidths=[2.4*inch, 1.3*inch, 1.3*inch, 1.4*inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                               ("GRID", (0, 0), (-1, -1), 0.4, GREY),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        fl.append(Spacer(1, 0.06 * inch))
        fl.append(t)
        fl.append(Spacer(1, 0.1 * inch))
        fl.append(_clause("1.2", f"Article 4.1 of the Agreement is hereby amended to extend the claims "
                  f"submission deadline from {am['old_timely_filing_days']} to "
                  f"{am['new_timely_filing_days']} calendar days from the date of service, effective "
                  f"{_fmt(am['effective'])}."))

    fl.append(Spacer(1, 0.3 * inch))
    sig = [
        ["PAYER:", "", "PROVIDER:"],
        [payer, "", cfg.HEALTH_SYSTEM],
        ["By: ______________________", "", "By: ______________________"],
        [f"Date: {_fmt(am['effective'])}", "", f"Date: {_fmt(am['effective'])}"],
    ]
    st = Table(sig, colWidths=[2.6 * inch, 0.6 * inch, 2.6 * inch])
    st.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
                            ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold")]))
    fl.append(st)
    doc.build(fl)
    return fname


def main():
    written = []
    for idx, payer in enumerate(cfg.PAYER_LIST, start=1):
        cno = f"NWH-2024-{idx:03d}"
        written.append(build_contract(payer, cno))
    # amendments reference their payer's contract number
    payer_cno = {payer: f"NWH-2024-{i:03d}" for i, payer in enumerate(cfg.PAYER_LIST, start=1)}
    for am in cfg.AMENDMENTS:
        written.append(build_amendment(am, payer_cno[am["payer"]]))

    print(f"wrote {len(written)} PDFs to {OUT}")
    for w in written:
        print("  ", os.path.basename(w))


if __name__ == "__main__":
    main()
