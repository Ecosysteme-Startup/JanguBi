<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbResetTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbResetIntro")}

${msg("jbResetButton")} :
${link}

${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbResetIgnore")}
</@layout.emailLayout>
