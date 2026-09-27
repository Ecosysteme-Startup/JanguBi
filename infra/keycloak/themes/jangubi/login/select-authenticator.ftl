<#import "template.ftl" as layout>
<#-- Choix de la méthode de connexion (« Utiliser une autre méthode »). -->
<@layout.registrationLayout displayInfo=false subtitle=msg("loginChooseAuthenticatorSubtitle"); section>
    <#if section = "header">
        ${msg("loginChooseAuthenticator")}
    <#elseif section = "form">
        <form id="kc-select-credential-form" class="jb-form" action="${url.loginAction}" method="post">
            <div class="jb-choices">
                <#list auth.authenticationSelections as authenticationSelection>
                    <button class="jb-choice" type="submit" name="authenticationExecution" value="${authenticationSelection.authExecId}">
                        <span class="jb-choice-icon" aria-hidden="true">
                            <#if authenticationSelection.displayName?contains("otp")>
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2"/><path d="M12 18h.01"/></svg>
                            <#else>
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                            </#if>
                        </span>
                        <span class="jb-choice-body">
                            <span class="jb-choice-title">${msg('${authenticationSelection.displayName}')}</span>
                            <span class="jb-choice-help">${msg('${authenticationSelection.helpText}')}</span>
                        </span>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
                    </button>
                </#list>
            </div>
        </form>
    </#if>
</@layout.registrationLayout>
