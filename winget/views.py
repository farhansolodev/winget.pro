from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import Package
from .util import load_tenant, return_jsonresponse, parse_jsonrequest


@require_GET
@load_tenant
def index(*_):
    # The sole motivation for this view is that we want to be able to
    # reverse('winget:index') in instructions for setting up the winget source.
    return HttpResponse("""
        <html>
        <head>
            <style>
                body {
                    font-family: 'Georgia', sans-serif;
                    background-color: #f8f8f8;
                    text-align: left;
                    padding: 20px;
                }

                #cta {
                    font-size: 20px;
                    color: #333;
                    padding: 20px;
                    line-height: 1.5;
                }

                code {
                    background-color: #e6e6e6;
                    padding: 2px 5px;
                    border-radius: 4px;
                    font-family: 'Arial', sans-serif;
                }
            </style>
        </head>
        <body>
            <p id="cta"></p>
            <script>
                const command = `winget source add -n farhansolodev -a ${window.location.href} -t "Microsoft.Rest"`;
                document.getElementById('cta').innerHTML = `To add this repo to your winget CLI, run: <code>${command}</code>.`;
            </script>
        </body>
    </html>
    """)


@require_GET
@load_tenant
@return_jsonresponse
def information(*_):
    return {
        'SourceIdentifier': 'api.winget.pro',
        'ServerSupportedVersions': ['1.4.0', '1.5.0']
    }


@require_POST
@csrf_exempt
@load_tenant
@parse_jsonrequest
@return_jsonresponse
def manifestSearch(_, data, tenant):
    db_query = Q(tenant=tenant)
    if 'Query' in data:
        keyword = data['Query']['KeyWord']
        db_query &= Q(name__icontains=keyword)
    inclusions_query = Q()
    for inclusion in data.get('Inclusions', []):
        field = inclusion['PackageMatchField']
        if field == 'PackageName':
            keyword = inclusion['RequestMatch']['KeyWord']
            inclusions_query |= Q(name__icontains=keyword)
        elif field == 'ProductCode':
            keyword = inclusion['RequestMatch']['KeyWord']
            # We don't have a ProductCode. Use the identifier instead.
            inclusions_query |= Q(identifier__icontains=keyword)
        elif field == 'PackageFamilyName':
            keyword = inclusion['RequestMatch']['KeyWord']
            # We don't have family name. Use the name instead.
            inclusions_query |= Q(name__icontains=keyword)
    db_query &= inclusions_query
    for filter_ in data.get('Filters', []):
        field = filter_['PackageMatchField']
        keyword = filter_['RequestMatch']['KeyWord']
        if field == 'PackageIdentifier':
            db_query &= Q(identifier__icontains=keyword)
    return [
        {
            'PackageIdentifier': package.identifier,
            'PackageName': package.name,
            'Publisher': package.publisher,
            'Versions': [
                {'PackageVersion': version.version}
                for version in package.version_set.all()
            ]
        }
        for package in Package.objects.filter(db_query)
        if package.version_set.exists()
    ]


@require_GET
@load_tenant
def packageManifests(request, tenant, identifier):
    try:
        package = Package.objects.get(tenant=tenant, identifier=identifier)
    except ObjectDoesNotExist:
        # This is a peculiarity / inconsistency of the winget client. The API
        # design docs say that packageManifests should return 404 when a package
        # does not exist. But winget doesn't gracefully handle this case.
        # Instead, it expects HTTP 204.
        # See: https://github.com/microsoft/winget-cli-restsource/issues/170
        return HttpResponse(status=204)
    return _packageManifests(request, package)


@return_jsonresponse
def _packageManifests(request, package):
    result = {
        'PackageIdentifier': package.identifier
    }
    for version in package.version_set.all():
        installers = []
        for installer in version.installer_set.all():
            for scope in installer.scopes:
                installer_json = {
                    'Architecture': installer.architecture,
                    'InstallerType': installer.type,
                    'InstallerUrl':
                        request.build_absolute_uri(installer.file.url),
                    'InstallerSha256': installer.sha256,
                    'Scope': scope
                }
                if installer.nested_installer:
                    # NestedInstallerFiles needs to be a list even though at
                    # least winget 1.6.2771 does not support more than one.
                    installer_json['NestedInstallerFiles'] = [{
                        'RelativeFilePath': installer.nested_installer
                    }]
                if installer.nested_installer_type:
                    installer_json['NestedInstallerType'] = \
                        installer.nested_installer_type
                switches = {
                    'Silent': installer.silent_switch,
                    'SilentWithProgress': installer.silent_progress_switch,
                    'Interactive': installer.interactive_switch,
                    'InstallLocation': installer.install_location_switch,
                    'Log': installer.log_switch,
                    'Upgrade': installer.upgrade_switch,
                    'Custom': installer.custom_switch
                }
                nonempty_switches = {k: v for k, v in switches.items() if v}
                if nonempty_switches:
                    installer_json['InstallerSwitches'] = nonempty_switches
                installers.append(installer_json)
        version_json = {
            'PackageVersion': version.version,
            'DefaultLocale': {
                'PackageLocale': 'en-us',
                'Publisher': package.publisher,
                'PackageName': package.name,
                'ShortDescription': package.description
            },
            'Installers': installers
        }
        result.setdefault('Versions', []).append(version_json)
    return result
