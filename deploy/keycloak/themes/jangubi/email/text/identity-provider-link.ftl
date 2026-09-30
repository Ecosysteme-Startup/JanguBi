<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbIdpTitle", identityProviderDisplayName) eyebrow=msg("jbSecurityEyebrow")>
${msg("jbIdpIntro", identityProviderDisplayName, identityProviderContext.username)}

${msg("jbIdpButton")} :
${link}

${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbIdpIgnore")}
</@layout.emailLayout>
