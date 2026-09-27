<#import "template.ftl" as layout>
<#-- Mot de passe oublié : même carte que WEB-Connexion. -->
<#assign userError = messagesPerField.existsError('username')>
<@layout.registrationLayout displayInfo=true displayMessage=!userError subtitle=msg("emailInstruction"); section>
    <#if section = "header">
        ${msg("emailForgotTitle")}
    <#elseif section = "form">
        <form id="kc-reset-password-form" class="jb-form" action="${url.loginAction}" method="post" novalidate>
            <div class="jb-field">
                <label for="username" class="jb-label">${msg("email")}</label>
                <input type="email" inputmode="email" id="username" name="username" class="jb-input" autofocus autocomplete="username" dir="ltr"
                       value="${(auth.attemptedUsername!'')}"
                       <#if userError>aria-invalid="true" aria-describedby="input-error-username"</#if>/>
                <#if userError>
                    <@layout.fieldError id="input-error-username">${kcSanitize(messagesPerField.get('username'))?no_esc}</@layout.fieldError>
                </#if>
            </div>
            <button class="jb-btn jb-btn-primary jb-btn-block" type="submit">${msg("doSendLink")}</button>
        </form>
    <#elseif section = "info">
        <a href="${url.loginUrl}">${msg("backToLoginLink")}</a>
    </#if>
</@layout.registrationLayout>
