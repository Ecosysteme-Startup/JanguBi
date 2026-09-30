<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbIdpTitle", identityProviderDisplayName) eyebrow=msg("jbSecurityEyebrow") preheader=msg("jbIdpPreheader", identityProviderDisplayName)>
<@layout.greeting/>
<@layout.p>${msg("jbIdpIntro", identityProviderDisplayName, identityProviderContext.username)}</@layout.p>
<@layout.button href=link label=msg("jbIdpButton")/>
<@layout.muted>${msg("jbLinkExpiry", linkExpirationFormatter(linkExpiration))} ${msg("jbIdpIgnore")}</@layout.muted>
<@layout.signature/>
</@layout.emailLayout>
