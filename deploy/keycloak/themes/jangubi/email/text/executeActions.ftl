<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbActionsTitle") eyebrow=msg("jbAccountEyebrow")>
${msg("jbActionsIntro")}
<#if requiredActions?? && requiredActions?has_content>
<#list requiredActions as action>
- ${msg("requiredAction.${action}")}
</#list>
</#if>

${msg("jbActionsButton")} :
${link}

${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbActionsIgnore")}
</@layout.emailLayout>
