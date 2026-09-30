<#import "template.ftl" as layout>
<#-- Nouveau mot de passe (lien « mot de passe oublié » ou action requise). -->
<#assign pwError = messagesPerField.existsError('password','password-confirm')>
<@layout.registrationLayout displayMessage=!pwError subtitle=msg("updatePasswordSubtitle"); section>
    <#if section = "header">
        ${msg("updatePasswordTitle")}
    <#elseif section = "form">
        <form id="kc-passwd-update-form" class="jb-form" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post" novalidate>
            <@layout.passwordField name="password-new" label=msg("passwordNew") autocomplete="new-password" invalid=pwError autofocus=true errorName="password"/>
            <@layout.passwordField name="password-confirm" label=msg("passwordConfirm") autocomplete="new-password" invalid=messagesPerField.existsError('password-confirm')/>

            <label class="jb-check">
                <input type="checkbox" id="logout-sessions" name="logout-sessions" value="on" checked>
                <span class="jb-box" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>
                ${msg("logoutOtherSessions")}
            </label>

            <div class="jb-actions">
                <button class="jb-btn jb-btn-primary jb-btn-block" name="login" type="submit">${msg("doSave")}</button>
                <#if isAppInitiatedAction??>
                    <button class="jb-btn jb-btn-outline jb-btn-block" type="submit" name="cancel-aia" value="true">${msg("doCancel")}</button>
                </#if>
            </div>
        </form>
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    </#if>
</@layout.registrationLayout>
