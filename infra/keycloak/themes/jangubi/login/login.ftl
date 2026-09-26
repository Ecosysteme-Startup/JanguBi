<#import "template.ftl" as layout>
<#import "passkeys.ftl" as passkeys>
<#-- WEB-Connexion : carte de 440 px, alerte, e-mail, mot de passe, « Rester connecté », création de compte,
     note au personnel sous la carte. -->
<#assign credentialsError = messagesPerField.existsError('username','password')>
<@layout.registrationLayout displayMessage=!credentialsError displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled?? subtitle=msg("loginSubtitle"); section>
    <#if section = "header">
        ${msg("loginAccountTitle")}
    <#elseif section = "form">
        <#if credentialsError>
            <@layout.alert type="error">${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}</@layout.alert>
        </#if>
        <#if realm.password>
            <form id="kc-form-login" class="jb-form" aria-label="${msg('loginFormLabel')}" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
                <#if !usernameHidden??>
                    <div class="jb-field">
                        <label for="username" class="jb-label">${msg("email")}</label>
                        <input id="username" class="jb-input" name="username" value="${(login.username!'')}" type="email" inputmode="email"
                               autofocus autocomplete="${(enableWebAuthnConditionalUI?has_content)?then('username webauthn', 'username')}" dir="ltr"
                               <#if credentialsError>aria-describedby="input-error"</#if>/>
                    </div>
                </#if>

                <div class="jb-field">
                    <div class="jb-label-row">
                        <label for="password" class="jb-label">${msg("password")}</label>
                        <#if realm.resetPasswordAllowed>
                            <a class="jb-link jb-hit" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
                        </#if>
                    </div>
                    <div class="jb-control jb-has-eye" dir="ltr">
                        <input id="password" class="jb-input" name="password" type="password" autocomplete="current-password"
                               <#if usernameHidden??>autofocus</#if>
                               <#if credentialsError>aria-invalid="true" aria-describedby="input-error"</#if>/>
                        <@layout.eye target="password"/>
                    </div>
                    <#if credentialsError>
                        <@layout.fieldError id="input-error">${msg("capsLockHint")}</@layout.fieldError>
                    </#if>
                </div>

                <#if realm.rememberMe && !usernameHidden??>
                    <label class="jb-check">
                        <input id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if>>
                        <span class="jb-box" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                        ${msg("rememberMe")}
                    </label>
                </#if>

                <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                <button class="jb-btn jb-btn-primary jb-btn-block" name="login" id="kc-login" type="submit">${msg("doLogIn")}</button>
            </form>
        </#if>
        <@passkeys.conditionalUIData />
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    <#elseif section = "info">
        ${msg("noAccount")} <a href="${url.registrationUrl}">${msg("doRegister")}</a>
    <#elseif section = "below">
        <p class="jb-below">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>
            <span>${msg("staffNotice")}</span>
        </p>
    </#if>
</@layout.registrationLayout>
