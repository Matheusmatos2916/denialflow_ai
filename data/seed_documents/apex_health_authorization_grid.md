# Apex Health Plan - Authorization and Referral Grid (Synthetic)

**Document:** AHP-AUTH-2023-07  
**Document status:** Synthetic training document; not an Apex Health Plan policy  
**Authority level:** Operational reference derived from public federal guidance; payer policy, plan terms, and provider agreement prevail  
**Scope:** Prior authorization, referrals, and emergency-service documentation for specialty services  
**Applicable product:** Example commercial plan; product-specific benefits control  
**Jurisdiction:** United States; confirm state and federal requirements  
**Effective date:** 2023-07-01  
**Last reviewed:** 2026-09-13  
**Source basis:** [HealthCare.gov preauthorization glossary](https://www.healthcare.gov/glossary/preauthorization/) and [emergency room access protections](https://www.healthcare.gov/health-care-law-protections/doctor-choice-emergency-room-access/)

## Purpose and limitations

This document models the fields and checks that an operational authorization grid should contain. It must not be used as evidence that a specific service requires authorization. The member's benefit document, payer policy, provider agreement, and policy version effective on the date of service take precedence.

Prior authorization is not a guarantee of payment. Eligibility, covered benefits, medical necessity, coding, and claim-submission requirements must be verified separately.

## Definitions

- **Prior authorization:** Payer decision required before a service when the applicable benefit requires it.
- **Referral:** Direction to a specialist when required by the member's product; it is not interchangeable with prior authorization.
- **Emergency service:** Service meeting the applicable legal and plan definition of an emergency medical condition.
- **Retroactive authorization:** A post-service request allowed only when the applicable payer policy or law expressly permits it.

## Authorization grid fields

The production version should maintain a versioned table with at least:

| Field | Required value |
|---|---|
| Service | CPT/HCPCS code or service description |
| Setting | Place of service and facility/provider type |
| Product | Plan, network, and benefit package |
| Requirement | Authorization, referral, notification, or none |
| Submission channel | Portal, telephone, fax, or EDI |
| Effective dates | Start and end date of the grid version |
| Source | Policy section, URL, or contract reference |

## Operational checks

Before claim submission, verify that the authorization record matches the member, date of service, approved CPT/HCPCS code, units, rendering provider, facility, place of service, and authorization start/end dates. Store the authorization number and payer transaction or call reference according to the payer's claim instructions; do not assume that every payer requires the number in the same claim field.

## Emergency and retroactive requests

Emergency services must be evaluated under the applicable law, plan, and notification requirements. For plans covered by the cited HealthCare.gov protections, prior approval cannot be required before covered out-of-network emergency room services. This does not eliminate the need to verify eligibility, coverage, post-service notification, or claim documentation.

Do not use a universal 72-hour rule. The production policy must record the exact deadline, whether it is measured in calendar or business hours, the notification channel, required attestation, and permitted exceptions. If a 72-hour rule is used, cite the payer policy section that establishes it.

## Common denial patterns

- Authorization or referral absent when required by the applicable product.
- Authorization inactive on the date of service.
- Billed code, units, provider, facility, or place of service differs from the approval.
- Required emergency notification or supporting attestation missing.

## Appeal evidence checklist

Include only evidence relevant to the denial: authorization approval, portal screenshot or transaction record, call reference with date and time, member and date-of-service match, approved-versus-billed code table, emergency documentation and attestation when applicable, and the precise policy section in force on the date of service.
