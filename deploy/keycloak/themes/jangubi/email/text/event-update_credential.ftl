<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbUpdateCredentialTitle") eyebrow=msg("jbSecurityEyebrow")>
${msg("jbUpdateCredentialIntro", event.date?datetime?string("dd/MM/yyyy"), event.date?datetime?string("HH:mm"), event.ipAddress)}

${msg("jbCredentialAdvice")}
</@layout.emailLayout>
