<#import "template.ftl" as layout>
<#import "passkeys.ftl" as passkeys>
<#-- PUB-Connexion : e-mail, mot de passe, « rester connecté », création de compte, note au personnel. -->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled?? eyebrow=msg("loginEyebrow") subtitle=msg("loginSubtitle"); section>
    <#if section = "header">
        ${msg("loginAccountTitle")}
    <#elseif section = "form">
        <#if realm.password>
            <form id="kc-form-login" class="jb-form" aria-label="Connexion à Jàngu Bi" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
                <#if !usernameHidden??>
                    <div class="jb-group">
                        <label for="username" class="jb-label">${msg("email")}</label>
                        <input id="username" class="jb-input" name="username" value="${(login.username!'')}" type="email" inputmode="email"
                               autofocus autocomplete="${(enableWebAuthnConditionalUI?has_content)?then('username webauthn', 'username')}"
                               <#if messagesPerField.existsError('username','password')>aria-invalid="true" aria-describedby="input-error"</#if> dir="ltr"/>
                    </div>
                </#if>

                <div class="jb-group">
                    <div class="jb-label-row">
                        <label for="password" class="jb-label">${msg("password")}</label>
                        <#if realm.resetPasswordAllowed>
                            <a class="jb-link" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
                        </#if>
                    </div>
                    <div class="jb-input-group" dir="ltr">
                        <input id="password" class="jb-input" name="password" type="password" autocomplete="current-password"
                               <#if messagesPerField.existsError('username','password')>aria-invalid="true" aria-describedby="input-error"</#if>/>
                        <button class="jb-eye" type="button" aria-label="${msg("showPassword")}" aria-controls="password" data-password-toggle
                                data-icon-show="jb-eye-show" data-icon-hide="jb-eye-hide"
                                data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                            <i class="jb-eye-show" aria-hidden="true"></i>
                        </button>
                    </div>
                    <#if messagesPerField.existsError('username','password')>
                        <span id="input-error" class="jb-error" aria-live="polite">${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}</span>
                    </#if>
                </div>

                <#if realm.rememberMe && !usernameHidden??>
                    <label class="jb-check">
                        <input id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if>> ${msg("rememberMe")}
                    </label>
                </#if>

                <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                <button class="jb-btn jb-btn-primary jb-btn-block jb-btn-lg" name="login" id="kc-login" type="submit">
                    ${msg("doLogIn")}
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 12h15M13.5 6l6 6-6 6"/></svg>
                </button>
            </form>
        </#if>
        <@passkeys.conditionalUIData />
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    <#elseif section = "info">
        <p class="jb-register-row">
            <span>${msg("noAccount")}</span>
            <a class="jb-btn jb-btn-secondary" href="${url.registrationUrl}">${msg("doRegister")}</a>
        </p>
        <div class="jb-notice" role="note">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 19 6v5.5c0 4.5-3 7.8-7 9.5-4-1.7-7-5-7-9.5V6z"/><path d="m9 12 2 2 4-4"/></svg>
            <div>
                <p class="jb-notice-title">${msg("staffNoticeTitle")}</p>
                <p class="jb-notice-body">${msg("staffNoticeBody")}</p>
            </div>
        </div>
    </#if>
</@layout.registrationLayout>
