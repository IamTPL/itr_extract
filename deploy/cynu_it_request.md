# ITR Extract — IT Setup Request for CYNU

**To:** CYNU IT / Microsoft 365 Administrator
**From:** Bestarion — ITR Extract project team (contact: Long Tran-Phi, longtp@bestarion.com)
**Purpose:** Enable Microsoft sign-in for the ITR Extract application — **2 quick actions, ~5 minutes total.**

---

## What is this?

**ITR Extract** is a web application Bestarion built for CYNU to extract data from tax-return PDFs. It is hosted at **https://itr.cynu.com** (a subdomain under your domain — the DNS record is already in place, and the site is live with HTTPS).

Your staff will sign in with their **existing CYNU Microsoft work accounts** — no new accounts, no new passwords. To enable this, Microsoft requires a one-time approval from your Entra ID administrator.

---

## Action 1 — Approve the application (admin consent)

1. Open this link and sign in with a **CYNU admin** account:

   ```
   https://login.microsoftonline.com/cynu.com/adminconsent?client_id=dca257ea-bb51-40cd-8e80-5e32abd9752e
   ```

2. Microsoft will display the permissions requested (see table below) → click **Accept**.
3. After accepting, the browser redirects to the application page — the approval is already recorded at that point.

> If the link shows a tenant-related error, replace `cynu.com` in the URL with your Tenant ID (see Action 2), then retry.

### Permissions requested — all **Delegated**

"Delegated" means the app acts **only on behalf of the signed-in user, only while they are using it**, and only within that user's own data.

| Permission | What the app uses it for | What it can **NOT** do |
|---|---|---|
| Sign in and read user profile (`User.Read`) | Read the user's name/email at sign-in | Cannot modify anything |
| Read and write access to user mail (`Mail.ReadWrite`) | Create a **draft** email containing the extraction results in the signed-in user's **own** mailbox, for them to review and send | Cannot send email (the app has no `Mail.Send`); cannot access any **other** user's mailbox; cannot run in the background without a signed-in user |
| Access ITR Extract API (`access_as_user`) | Lets the signed-in user call the application's own API | — |

### Your control after approval

- The app appears in **your** portal under **Microsoft Entra ID → Enterprise applications → ITR_Extraction**. There you can review the granted permissions and your users' sign-in logs at any time.
- **You can revoke access entirely, at any time**: deleting that enterprise application immediately disables the app for all CYNU users. No involvement from Bestarion is needed.
- If the application ever requests **additional** permissions in the future, Microsoft will require your admin's approval again — permissions cannot expand silently.

---

## Action 2 — Send us your Tenant ID

1. Go to **portal.azure.com** → **Microsoft Entra ID** → **Overview**.
2. Copy the **Tenant ID** (a GUID such as `1234abcd-56ef-...`). It is a public identifier, **not a secret**.
3. Reply to us with that value.

Once we receive it, we will configure the application to accept sign-ins **exclusively from CYNU accounts** — any other Microsoft account (other organizations, personal accounts) will be rejected — and confirm go-live with you.

---

## Optional (recommended) — Limit which employees can use the app

If you prefer to restrict the app to specific staff members:

1. **Entra ID → Enterprise applications → ITR_Extraction → Properties** → set **"Assignment required?" = Yes** → Save.
2. **Users and groups → Add user/group** → add the specific employees.

Only the users you list will be able to sign in; everyone else in your organization is blocked at the Microsoft login page. (Individual-user assignment is available on standard Microsoft 365 plans; assigning whole groups requires Entra ID P1.)

---

## Questions?

Contact: **Long Tran-Phi** — longtp@bestarion.com. We are happy to walk through any of the above on a call.
