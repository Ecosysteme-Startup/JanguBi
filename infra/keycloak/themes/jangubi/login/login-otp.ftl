<#import "template.ftl" as layout>
<#-- Double vérification du personnel (EF-AUTH-05) : code TOTP à 6 chiffres, même carte que WEB-Connexion. -->
<#assign otpError = messagesPerField.existsError('totp')>
<@layout.registrationLayout displayMessage=!otpError subtitle=msg("otpSubtitle"); section>
    <#if section = "header">
        ${msg("otpTitle")}
    <#elseif section = "form">
        <#if otpError>
            <@layout.alert type="error">${kcSanitize(messagesPerField.get('totp'))?no_esc}</@layout.alert>
        </#if>
        <form id="kc-otp-login-form" class="jb-form" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
            <#if otpLogin.userOtpCredentials?size gt 1>
                <fieldset class="jb-field" style="border:0;padding:0;margin-inline:0">
                    <legend class="jb-label">${msg("otpDevice")}</legend>
                    <#list otpLogin.userOtpCredentials as otpCredential>
                        <label class="jb-check jb-check-sm">
                            <input type="radio" name="selectedCredentialId" value="${otpCredential.id}" <#if otpCredential.id == otpLogin.selectedCredentialId>checked</#if>>
                            <span class="jb-box" style="border-radius:50%" aria-hidden="true"><svg width="8" height="8" viewBox="0 0 8 8"><circle cx="4" cy="4" r="4" fill="currentColor"/></svg></span>
                            ${otpCredential.userLabel}
                        </label>
                    </#list>
                </fieldset>
            </#if>
            <div class="jb-field">
                <label for="otp" class="jb-label">${msg("loginOtpOneTime")}</label>
                <input id="otp" name="otp" autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]*" maxlength="6" type="text"
                       class="jb-input jb-input-otp" autofocus dir="ltr"
                       <#if otpError>aria-invalid="true" aria-describedby="input-error-otp-code"</#if>/>
                <#if otpError>
                    <span id="input-error-otp-code" class="jb-sr">${kcSanitize(messagesPerField.get('totp'))?no_esc}</span>
                </#if>
            </div>
            <button class="jb-btn jb-btn-primary jb-btn-block" name="login" id="kc-login" type="submit">${msg("doLogIn")}</button>
        </form>
    </#if>
</@layout.registrationLayout>
