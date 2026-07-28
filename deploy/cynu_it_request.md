# ITR Extract — Microsoft 365 Setup Guide

**For:** CYNU
**From:** Bestarion — ITR Extract team (Long Tran-Phi, longtp@bestarion.com)

The ITR Extract application is live at **https://itr.cynu.com**. Your staff will sign in with their existing CYNU Microsoft work emails — no new accounts or passwords.

Before that works, Microsoft requires a **one-time approval** from your organization. This guide shows how to do it yourself (**~10 minutes, 2 steps**). If you'd rather have us handle it, see the last section.

> **Which account to use:** the Microsoft 365 **administrator** account — the one used to manage your company email and users (it can sign in at admin.microsoft.com). It's usually the account used when your company email was first set up.

---

## Step 1 — Approve the application (one click)

1. Copy this link into your browser and sign in with the admin account:

   ```
   https://login.microsoftonline.com/cynu.com/adminconsent?client_id=dca257ea-bb51-40cd-8e80-5e32abd9752e
   ```

2. Microsoft shows a "Permissions requested" screen listing exactly the items below → click **Accept**.
3. The browser then opens the application page (https://itr.cynu.com) — that means the approval is recorded. Done.

**What you are approving** — all permissions are "Delegated", meaning the app acts only on behalf of the person signed in, only while they use it:

| Permission shown | What the app uses it for | What it can NOT do |
|---|---|---|
| Sign in and read user profile | Read the user's name/email at sign-in | Modify anything |
| Read and write access to user mail | Create a **draft** email with the extraction results in the signed-in user's **own** mailbox | Send email; access anyone **else's** mailbox; run in the background |
| Access ITR Extract API | Let the signed-in user use the application | — |

> If the link shows an error mentioning the tenant, do Step 2 first, then replace `cynu.com` in the link with your Tenant ID and retry.

## Step 2 — Send us your Tenant ID

1. Go to **portal.azure.com** and sign in with the same admin account.
2. In the menu, open **Microsoft Entra ID** → you land on **Overview**.
3. Copy the value labeled **Tenant ID** (looks like `1234abcd-56ef-...`) and email it to us. It's an identifier, **not a secret**.

Once we have it, we lock the application so that **only CYNU accounts** can sign in — every other Microsoft account (other companies, personal accounts) is rejected. We'll confirm go-live with you right after.

## Optional — Limit which employees can use the app

If you want only specific staff to have access: in **portal.azure.com → Microsoft Entra ID → Enterprise applications → ITR_Extraction** → **Properties** → set **"Assignment required?" = Yes** → Save, then add the employees under **Users and groups**. We're happy to help with this — just ask.

## Good to know — you stay in control

- After approval, the app appears in **your** portal (Entra ID → Enterprise applications → ITR_Extraction). You can review permissions and sign-in activity there anytime.
- **You can revoke everything at any time** by deleting that entry — the app immediately stops working for all CYNU users.
- If the app ever needs additional permissions in the future, Microsoft will ask for your approval again — permissions cannot expand silently.

---

## Having trouble? We can handle it for you

If any of the above is unclear, or you'd prefer not to do it yourself, we can take care of these steps on your behalf — the same way we handled the domain setup:

1. Reply with your **Microsoft 365 admin email address** (no password yet);
2. Suggest a convenient time — at that point we'll need a **temporary password** (you can change it right after we're done) and a **verification code** Microsoft may text to your phone.

We will only perform the steps in this guide — nothing else in your Microsoft settings will be changed.

**Contact:** Long Tran-Phi — longtp@bestarion.com
