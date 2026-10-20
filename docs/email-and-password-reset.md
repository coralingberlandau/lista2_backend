[← Back to the README](../Readme.md)

# Email and Password Reset

1. The user asks for a reset on the **Forgot password** screen: `POST /reset_password_request/` with their email.  
2. The backend creates a **single-use token** (valid for **one hour**, tied to the account and its current password) and sends 
   an email through **Brevo** with the link `FRONTEND_URL/change-password?email=...&token=...`.  
3. The link opens the Change Password screen; the app sends `email`, `token` and the new password to `POST /reset_password/`.  
4. The backend checks the token and the password rules, then saves the new password. The token stops working immediately.  
5. If the email cannot be sent the API answers **502**, and the app shows *"Couldn't send the reset link"*.  

**Brevo setup (once):** create a free account, add and verify your sender address (Senders), then create an API key (SMTP & API > API keys) 
and put it in `BREVO_API_KEY`. The free plan allows 300 emails a day and has no expiry.  
**Good to know:** without your own domain, Brevo replaces the sender with an address on its own domain, so the email arrives as, 
for example, *Lista <listaassistance@12345.brevosend.com>*. It is delivered normally; authenticating your own domain in Brevo removes this.
