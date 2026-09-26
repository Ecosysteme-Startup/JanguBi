<#import "template.ftl" as layout>
<#import "user-profile-commons.ftl" as userProfileCommons>
<#-- Compléter le profil (action requise) : champs du profil utilisateur, même carte que WEB-Connexion. -->
<@layout.registrationLayout displayMessage=messagesPerField.exists('global') subtitle=msg("loginProfileSubtitle"); section>
    <#if section = "header">
        ${msg("loginProfileTitle")}
    <#elseif section = "form">
        <form id="kc-update-profile-form" class="jb-form" action="${url.loginAction}" method="post" novalidate>
            <@userProfileCommons.userProfileFormFields/>
            <div class="jb-actions">
                <button class="jb-btn jb-btn-primary jb-btn-block" type="submit">${msg("doContinue")}</button>
                <#if isAppInitiatedAction??>
                    <button class="jb-btn jb-btn-outline jb-btn-block" type="submit" name="cancel-aia" value="true" formnovalidate>${msg("doCancel")}</button>
                </#if>
            </div>
        </form>
    </#if>
</@layout.registrationLayout>
