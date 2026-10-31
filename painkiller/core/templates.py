"""The built-in project templates: every project is born from one of them.

Painkiller Android fabrica apps Android em React + Ionic empacotados com
Capacitor. O template nativo em Kotlin continua semeado, mas inativo: projetos
antigos seguem funcionando com ele, e nenhum projeto novo nasce dele. Os
templates existem sempre (semeados no startup) e o admin só os configura:
nome, descrição, diretrizes para os agentes, skill e um arcabouço .zip que
substitui o embutido.
"""

import os
from dataclasses import dataclass
from typing import Any, Optional

from painkiller.core.domain.models import ProjectTemplate, ProjectType

ANDROID_TEMPLATE_ID = "android-kotlin"
CAPACITOR_TEMPLATE_ID = "capacitor-react"

#: Projetos anteriores à escolha de template nasceram do Android nativo.
LEGACY_TEMPLATE_ID = ANDROID_TEMPLATE_ID
#: Todo projeto novo nasce do Capacitor, o único template ativo.
DEFAULT_TEMPLATE_ID = CAPACITOR_TEMPLATE_ID

SCAFFOLDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scaffolds")


@dataclass(frozen=True)
class BuiltinTemplate:
    id: str
    name: str
    description: str
    project_type: ProjectType
    #: Diretrizes padrão para os agentes; o admin pode reescrevê-las.
    prompt: str
    #: Inativo: o template segue servindo projetos antigos, mas não aparece na criação.
    active: bool = True

    @property
    def scaffold_dir(self) -> str:
        """Arcabouço embutido, usado enquanto o admin não sobe um .zip próprio."""
        return os.path.join(SCAFFOLDS_DIR, self.id)

    @property
    def scaffold_filename(self) -> str:
        return f"{self.id}.zip"


ANDROID_TEMPLATE = BuiltinTemplate(
    id=ANDROID_TEMPLATE_ID,
    name="Android nativo (Kotlin)",
    description="App Android nativo em Kotlin com Jetpack Compose, Material 3 e Gradle (Kotlin DSL).",
    project_type=ProjectType.ANDROID_NATIVE,
    active=False,
    prompt=(
        "- Linguagem: Kotlin. UI em Jetpack Compose com Material 3; nada de XML de layout nem Views.\n"
        "- Build com o Gradle wrapper do repositório (Kotlin DSL, version catalog em gradle/libs.versions.toml). "
        "Novas dependências entram no catálogo, nunca com versão solta no build.gradle.kts.\n"
        "- Arquitetura: camadas ui/ (telas + ViewModel com StateFlow), data/ (repositórios) e, quando houver "
        "regra de negócio, domain/. Navegação com Navigation 3.\n"
        "- Testes unitários em app/src/test (JUnit 4, kotlinx-coroutines-test) para ViewModels e regras de "
        "negócio; eles precisam passar com ./gradlew testDebugUnitTest. Testes instrumentados (androidTest) "
        "não rodam aqui: não há emulador.\n"
        "- Textos visíveis ao usuário em res/values/strings.xml.\n"
        "- Na primeira tarefa, troque o pacote de exemplo com.example.myapp (namespace, applicationId e "
        "pastas) por um pacote próprio do app."
    ),
)

CAPACITOR_TEMPLATE = BuiltinTemplate(
    id=CAPACITOR_TEMPLATE_ID,
    name="Android com Capacitor (React)",
    description="App Android em React + Ionic, empacotado com Capacitor; Vite, TypeScript e Vitest.",
    project_type=ProjectType.CAPACITOR_REACT,
    prompt=(
        "- Linguagem: TypeScript estrito. UI em React 19 com componentes do Ionic React (IonPage, IonHeader, "
        "IonContent, IonList...) no modo Material Design; não monte do zero o que o Ionic já tem.\n"
        "- Rotas com react-router 6 dentro de IonReactRouter/IonRouterOutlet (<Route path element>), como em "
        "src/App.tsx. Não suba o react-router para a v7: o @ionic/react-router não aceita.\n"
        "- Arquitetura: src/pages/ (uma pasta ou arquivo por tela, com o estado num hook useAlgo ao lado), "
        "src/components/ (peças reutilizáveis), src/data/ (repositórios: fetch, armazenamento, plugins do "
        "Capacitor). A tela só renderiza; a lógica fica no hook e no repositório, que recebem dependências "
        "por parâmetro para poderem ser testados.\n"
        "- Testes com Vitest + Testing Library (arquivos *.test.ts(x) ao lado do código) para hooks, "
        "repositórios e telas; eles precisam passar com npm test, e npm run build não pode ter erro de tipo.\n"
        "- Recursos nativos (câmera, arquivos, notificações, armazenamento) via plugins oficiais @capacitor/*, "
        "sempre com um repositório em src/data/ que o teste substitui. Só mexa em android/ quando um plugin "
        "ou permissão exigir.\n"
        "- Na primeira tarefa, troque o appId de exemplo com.example.myapp (capacitor.config.ts, "
        "android/app/build.gradle e o pacote Java em android/app/src) e o nome My App por um próprio do app."
    ),
)

BUILTIN_TEMPLATES: dict[str, BuiltinTemplate] = {
    t.id: t for t in (ANDROID_TEMPLATE, CAPACITOR_TEMPLATE)
}


def builtin_template(template_id: Optional[str]) -> BuiltinTemplate:
    """The built-in template of a project; unknown or empty ids are the legacy native Android one."""
    return BUILTIN_TEMPLATES.get(template_id or "", BUILTIN_TEMPLATES[LEGACY_TEMPLATE_ID])


def project_type_of(project: Any) -> ProjectType:
    return builtin_template(getattr(project, "template_id", None)).project_type


def has_uploaded_scaffold(template: ProjectTemplate) -> bool:
    return bool(template.scaffold_path and os.path.exists(template.scaffold_path))


async def ensure_builtin_templates(tracker: Any) -> list[ProjectTemplate]:
    """Create the built-in templates when missing and drop any other template.

    Bancos vindos da edição generalista podem ter outros templates: aqui só os
    embutidos existem. O estado ativo de cada um é fixo (``BuiltinTemplate.active``):
    o admin não liga nem desliga templates.
    """
    for other in await tracker.list_project_templates():
        if other.id not in BUILTIN_TEMPLATES:
            await tracker.delete_project_template(other.id)
    templates: list[ProjectTemplate] = []
    for spec in BUILTIN_TEMPLATES.values():
        template = await tracker.get_project_template(spec.id)
        if template is None:
            template = await tracker.create_project_template(
                template_id=spec.id,
                name=spec.name,
                description=spec.description,
                project_type=spec.project_type,
                coolify_compatible=False,
                prompt=spec.prompt,
                is_active=spec.active,
            )
        elif template.is_active != spec.active:
            template = await tracker.update_project_template(spec.id, is_active=spec.active) or template
        templates.append(template)
    return templates


async def template_guidelines(tracker: Any, template_id: Optional[str]) -> str:
    """The admin's guidelines for the agents of a project's template, or '' when unavailable."""
    try:
        template = await tracker.get_project_template(builtin_template(template_id).id)
    except Exception:
        return ""
    prompt = getattr(template, "prompt", "")
    return prompt.strip() if isinstance(prompt, str) else ""
