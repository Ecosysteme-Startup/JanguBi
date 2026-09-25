<#import "template.ftl" as layout>
<#-- Double vérification du personnel (EF-AUTH-05) : code TOTP à 6 chiffres. -->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('totp') eyebrow=msg("otpEyebrow") subtitle=msg("otpSubtitle"); section>
    <#if section = "header">
        ${msg("otpTitle")}
    <#elseif section = "form">
        <form id="kc-otp-login-form" class="jb-form" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
            <#if otpLogin.userOtpCredentials?size gt 1>
                <fieldset class="jb-group jb-fieldset">
                    <legend class="jb-label">Appareil</legend>
                    <#list otpLogin.userOtpCredentials as otpCredential>
                        <label class="jb-check">
                            <input type="radio" name="selectedCredentialId" value="${otpCredential.id}" <#if otpCredential.id == otpLogin.selectedCredentialId>checked</#if>>
                            ${otpCredential.userLabel}
                        </label>
                    </#list>
                </fieldset>
            </#if>
            <div class="jb-group">
                <label for="otp" class="jb-label">${msg("loginOtpOneTime")}</label>
                <input id="otp" name="otp" autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]*" maxlength="6" type="text"
                       class="jb-input jb-input-otp" autofocus dir="ltr"
                       <#if messagesPerField.existsError('totp')>aria-invalid="true" aria-describedby="input-error-otp-code"</#if>/>
                <#if messagesPerField.existsError('totp')>
                    <span id="input-error-otp-code" class="jb-error" aria-live="polite">${kcSanitize(messagesPerField.get('totp'))?no_esc}</span>
                </#if>
            </div>
            <button class="jb-btn jb-btn-primary jb-btn-block jb-btn-lg" name="login" id="kc-login" type="submit">${msg("doLogIn")}</button>
        </form>
    </#if>
</@layout.registrationLayout>
