<#ftl output_format="plainText">
<#-- Gabarit texte des e-mails Jàngu Bi (même contenu que la version HTML). -->
<#function jbWebUrl>
    <#local configured = (properties.jbWebUrl!'')?trim>
    <#if configured?starts_with("http")><#return configured?remove_ending("/")></#if>
    <#return "">
</#function>
<#macro emailLayout title="" eyebrow="">
<#local web = jbWebUrl()>
JÀNGU BI
<#if eyebrow?has_content>
${eyebrow?upper_case}
</#if>
<#if title?has_content>
${title}
</#if>

<#if user?? && (user.firstName!'')?has_content>${msg("jbGreeting", user.firstName)}<#else>${msg("jbGreetingAnonymous")}</#if>

<#nested>

${msg("jbSignature")}
${msg("jbTeam")}

--
${msg("jbFooterDiocese")}
${msg("jbFooterTagline")}
${msg("jbFooterAuto")}
<#if web?has_content>
${msg("jbFooterHelp")} ${web}/pour-les-paroisses#contact
${msg("jbFooterPrivacy")} : ${web}/confidentialite
</#if>
${msg("jbFooterLaw")}
${msg("jbFooterCopyright", .now?string("yyyy"))}
</#macro>
