<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbVerifyTitle") eyebrow=msg("jbVerifyEyebrow")>
${msg("jbVerifyIntro")}

${msg("jbVerifyButton")} :
${link}

${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbVerifyIgnore")}
</@layout.emailLayout>
