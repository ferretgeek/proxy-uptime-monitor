[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $CredentialPath,

    [Parameter(Mandatory)]
    [string] $PasswordOnlyPath,

    [Parameter(Mandatory)]
    [string] $AccessHost,

    [int] $Port = 18080
)

$ErrorActionPreference = 'Stop'

function Set-OwnerOnlyAcl {
    param([Parameter(Mandatory)][string] $LiteralPath)

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $security = [System.Security.AccessControl.FileSecurity]::new()
    $security.SetOwner($identity.User)
    $security.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($rule)
    Set-Acl -LiteralPath $LiteralPath -AclObject $security
}

$random = [byte[]]::new(24)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($random)
$body = [Convert]::ToBase64String($random).TrimEnd('=').Replace('+', 'A').Replace('/', 'z')
$password = "Am9!${body}"

$credentialFullPath = [System.IO.Path]::GetFullPath($CredentialPath)
$passwordFullPath = [System.IO.Path]::GetFullPath($PasswordOnlyPath)
[System.IO.Directory]::CreateDirectory(
    [System.IO.Path]::GetDirectoryName($credentialFullPath)
) | Out-Null
[System.IO.Directory]::CreateDirectory(
    [System.IO.Path]::GetDirectoryName($passwordFullPath)
) | Out-Null

$credentialText = @(
    '航迹监测平台管理员凭据'
    ''
    '管理员账号：admin'
    "管理员密码：$password"
    "访问地址：http://${AccessHost}:$Port/"
    ''
    '此文件包含敏感信息，请勿发送、截图或上传。'
) -join "`r`n"

[System.IO.File]::WriteAllText(
    $credentialFullPath,
    $credentialText + "`r`n",
    [System.Text.UTF8Encoding]::new($false)
)
[System.IO.File]::WriteAllText(
    $passwordFullPath,
    $password + "`n",
    [System.Text.UTF8Encoding]::new($false)
)
Set-OwnerOnlyAcl -LiteralPath $credentialFullPath
Set-OwnerOnlyAcl -LiteralPath $passwordFullPath
