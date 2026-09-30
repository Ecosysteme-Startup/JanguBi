<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbActionsTitle") eyebrow=msg("jbAccountEyebrow") preheader=msg("jbActionsPreheader")>
<@layout.greeting/>
<@layout.p>${msg("jbActionsIntro")}</@layout.p>
<#if requiredActions?? && requiredActions?has_content>
<ul style="margin: 0 0 16px; padding-left: 22px;">
<#list requiredActions as action><li style="margin: 0 0 8px;">${msg("requiredAction.${action}")}</li></#list>
</ul>
</#if>
<@layout.button href=link label=msg("jbActionsButton")/>
<@layout.muted>${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbActionsIgnore")}</@layout.muted>
<@layout.signature/>
</@layout.emailLayout>
