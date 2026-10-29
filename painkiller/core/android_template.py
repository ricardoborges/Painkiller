"""The single project template of this edition: a native Android app in Kotlin.

Painkiller Android só fabrica apps Android nativos. O template existe sempre
(semeado no startup) e o admin só o configura: nome, descrição, diretrizes
para os agentes, skill e um arcabouço .zip que substitui o embutido.
"""

import os
from typing import Any

from painkiller.core.domain.models import ProjectTemplate, ProjectType

ANDROID_TEMPLATE_ID = "android-kotlin"

DEFAULT_NAME = "Android nativo (Kotlin)"

DEFAULT_DESCRIPTION = "App Android nativo em Kotlin com Jetpack Compose, Material 3 e Gradle (Kotlin DSL)."

#: Diretrizes padrão para os agentes; o admin pode reescrevê-las.
DEFAULT_PROMPT = (
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
)

#: Arcabouço embutido, usado enquanto o admin não sobe um .zip próprio.
BUNDLED_SCAFFOLD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scaffolds", "android-kotlin")

BUNDLED_SCAFFOLD_FILENAME = "android-kotlin.zip"


def has_uploaded_scaffold(template: ProjectTemplate) -> bool:
    return bool(template.scaffold_path and os.path.exists(template.scaffold_path))


async def ensure_android_template(tracker: Any) -> ProjectTemplate:
    """Create the Android template when missing and drop any other template.

    Bancos vindos da edição generalista podem ter outros templates: aqui só um
    existe. Ele fica sempre ativo, porque todo projeto nasce dele.
    """
    for other in await tracker.list_project_templates():
        if other.id != ANDROID_TEMPLATE_ID:
            await tracker.delete_project_template(other.id)
    template = await tracker.get_project_template(ANDROID_TEMPLATE_ID)
    if template is None:
        return await tracker.create_project_template(
            template_id=ANDROID_TEMPLATE_ID,
            name=DEFAULT_NAME,
            description=DEFAULT_DESCRIPTION,
            project_type=ProjectType.ANDROID_NATIVE,
            coolify_compatible=False,
            prompt=DEFAULT_PROMPT,
            is_active=True,
        )
    if not template.is_active:
        template = await tracker.update_project_template(ANDROID_TEMPLATE_ID, is_active=True) or template
    return template


async def template_guidelines(tracker: Any) -> str:
    """The admin's guidelines for the agents, or '' when unavailable."""
    try:
        template = await tracker.get_project_template(ANDROID_TEMPLATE_ID)
    except Exception:
        return ""
    prompt = getattr(template, "prompt", "")
    return prompt.strip() if isinstance(prompt, str) else ""
