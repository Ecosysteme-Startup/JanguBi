<#import "template.ftl" as layout>
<#-- Confirmation de déconnexion. -->
<@layout.registrationLayout subtitle=msg("logoutConfirmHeader"); section>
    <#if section = "header">
        ${msg("logoutConfirmTitle")}
    <#elseif section = "form">
        <div id="kc-logout-confirm">
            <form class="jb-form" action="${url.logoutConfirmAction}" onsubmit="confirmLogout.disabled = true; return true;" method="POST">
                <input type="hidden" name="session_code" value="${logoutConfirm.code}">
                <div class="jb-actions">
                    <button class="jb-btn jb-btn-primary jb-btn-block" name="confirmLogout" id="kc-logout" type="submit" value="${msg('doLogout')}">${msg("doLogout")}</button>
                    <#if !logoutConfirm.skipLink && (client.baseUrl)?has_content>
                        <a class="jb-btn jb-btn-outline jb-btn-block" href="${client.baseUrl}">${kcSanitize(msg("backToApplication"))?no_esc}</a>
                    </#if>
                </div>
            </form>
        </div>
    </#if>
</@layout.registrationLayout>
