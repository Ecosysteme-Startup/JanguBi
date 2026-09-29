<#import "template.ftl" as layout>
<#-- Informations (e-mail confirmé, compte mis à jour, actions requises…). -->
<@layout.registrationLayout displayMessage=false; section>
    <#if section = "header">
        <#if messageHeader??>${kcSanitize(msg("${messageHeader}"))?no_esc}<#else>${msg("infoTitle")}</#if>
    <#elseif section = "form">
        <div id="kc-info-message">
            <@layout.alert type=(message.type)!"info">${message.summary}<#if requiredActions??><#list requiredActions> <#items as reqActionItem>${kcSanitize(msg("requiredAction.${reqActionItem}"))?no_esc}<#sep>, </#items>.</#list></#if></@layout.alert>
            <#if !skipLink??>
                <div class="jb-actions">
                    <#if pageRedirectUri?has_content>
                        <a class="jb-btn jb-btn-primary jb-btn-block" href="${pageRedirectUri}">${kcSanitize(msg("backToApplication"))?no_esc}</a>
                    <#elseif actionUri?has_content>
                        <a class="jb-btn jb-btn-primary jb-btn-block" href="${actionUri}">${kcSanitize(msg("proceedWithAction"))?no_esc}</a>
                    <#elseif (client.baseUrl)?has_content>
                        <a class="jb-btn jb-btn-primary jb-btn-block" href="${client.baseUrl}">${kcSanitize(msg("backToApplication"))?no_esc}</a>
                    </#if>
                </div>
            </#if>
        </div>
    </#if>
</@layout.registrationLayout>
