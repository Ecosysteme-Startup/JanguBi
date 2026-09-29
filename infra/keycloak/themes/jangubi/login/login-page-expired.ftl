<#import "template.ftl" as layout>
<#-- Page expirée (retour arrière, onglet resté ouvert). -->
<@layout.registrationLayout; section>
    <#if section = "header">
        ${msg("pageExpiredTitle")}
    <#elseif section = "form">
        <p class="jb-text" id="instruction1">${msg("pageExpiredMsg1")} ${msg("pageExpiredMsg2")}</p>
        <div class="jb-actions">
            <a id="loginRestartLink" class="jb-btn jb-btn-primary jb-btn-block" href="${url.loginRestartFlowUrl}">${msg("pageExpiredRestart")}</a>
            <a id="loginContinueLink" class="jb-btn jb-btn-outline jb-btn-block" href="${url.loginAction}">${msg("pageExpiredContinue")}</a>
        </div>
    </#if>
</@layout.registrationLayout>
