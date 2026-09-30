<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdateEmailTitle") eyebrow=msg("jbAccountEyebrow")>
${msg("jbUpdateEmailIntro", newEmail)}

${msg("jbUpdateEmailButton")} :
${link}

${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbUpdateEmailIgnore")}
</@layout.emailLayout>
