<#import "template.ftl" as layout>
<#-- Erreur (lien expiré ou déjà utilisé, client inconnu…). -->
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        ${kcSanitize(msg("errorTitle"))?no_esc}
    <#elseif section = "form">
        <div id="kc-error-message">
            <#if message?has_content>
                <@layout.alert type="error">${kcSanitize(message.summary)?no_esc}</@layout.alert>
            </#if>
            <#if !skipLink??>
                <div class="jb-actions">
                    <#if client?? && client.baseUrl?has_content>
                        <a id="backToApplication" class="jb-btn jb-btn-primary jb-btn-block" href="${client.baseUrl}">${kcSanitize(msg("backToApplication"))?no_esc}</a>
                    <#else>
                        <a id="backToApplication" class="jb-btn jb-btn-primary jb-btn-block" href="${properties.jbWebUrl!}/">${kcSanitize(msg("backToApplication"))?no_esc}</a>
                    </#if>
                </div>
            </#if>
        </div>
    </#if>
</@layout.registrationLayout>
