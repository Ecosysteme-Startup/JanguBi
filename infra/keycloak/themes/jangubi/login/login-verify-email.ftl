<#import "template.ftl" as layout>
<#-- Vérification de l'adresse e-mail (après l'inscription). -->
<@layout.registrationLayout displayInfo=!isAppInitiatedAction??; section>
    <#if section = "header">
        ${msg("emailVerifyTitle")}
    <#elseif section = "form">
        <p class="jb-text">
            <#if verifyEmail??>
                ${msg("emailVerifyInstruction1", verifyEmail)}
            <#else>
                ${msg("emailVerifyInstruction4", user.email)}
            </#if>
        </p>
        <#if isAppInitiatedAction??>
            <form id="kc-verify-email-form" class="jb-form" action="${url.loginAction}" method="post">
                <div class="jb-actions">
                    <#if verifyEmail??>
                        <button class="jb-btn jb-btn-primary jb-btn-block" type="submit">${msg("emailVerifyResend")}</button>
                    <#else>
                        <button class="jb-btn jb-btn-primary jb-btn-block" type="submit">${msg("emailVerifySend")}</button>
                    </#if>
                    <button class="jb-btn jb-btn-outline jb-btn-block" type="submit" name="cancel-aia" value="true" formnovalidate>${msg("doCancel")}</button>
                </div>
            </form>
        </#if>
    <#elseif section = "info">
        ${msg("emailVerifyInstruction2")} <a href="${url.loginAction}">${msg("emailVerifyInstruction3")}</a>.
    </#if>
</@layout.registrationLayout>
