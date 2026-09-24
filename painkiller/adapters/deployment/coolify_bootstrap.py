"""Unattended Coolify setup: root account, API access and an API token.

O Coolify não tem API para emitir o primeiro token (precisaria de um token
para isso), então isto roda PHP dentro do contêiner dele, via `docker exec
... php artisan tinker`, com o socket Docker que a API do Painkiller já tem.
Depende do esquema interno do Coolify (User/Team 0, `instanceSettings()`,
tokens Sanctum com `team_id`), conferido na 4.3; se uma versão nova mudar
isso, a automação falha com a mensagem do PHP e o tutorial manual continua
valendo.
"""

import asyncio
import json
import logging
import os
import secrets
import string
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Marca a linha de resultado no meio da saída do tinker.
RESULT_MARKER = "PAINKILLER_JSON:"

#: Nome do token que a automação emite; um novo substitui o anterior.
TOKEN_NAME = "painkiller"

_INSPECT_PHP = r"""
$user = \App\Models\User::find(0);
$settings = instanceSettings();
echo 'PAINKILLER_JSON:' . json_encode([
    'root_user' => $user !== null,
    'root_email' => $user ? $user->email : null,
    'api_enabled' => (bool) $settings->is_api_enabled,
]);
"""

# Credenciais chegam por variável de ambiente do exec, nunca interpoladas no PHP.
_PROVISION_PHP = r"""
$out = ['created_user' => false];
try {
    // Tudo ou nada: uma falha no meio não deixa conta sem time nem API ligada sem token.
    \Illuminate\Support\Facades\DB::transaction(function () use (&$out) {
        $team = \App\Models\Team::find(0);
        if ($team === null) {
            throw new \RuntimeException('O time raiz (id 0) ainda não existe: o Coolify terminou de subir?');
        }
        $user = \App\Models\User::find(0);
        if ($user === null) {
            $user = (new \App\Models\User)->forceFill([
                'id' => 0,
                'name' => 'Painkiller',
                'email' => getenv('PK_COOLIFY_EMAIL'),
                'password' => \Illuminate\Support\Facades\Hash::make(getenv('PK_COOLIFY_PASSWORD')),
            ]);
            $user->save();
            // O evento de criação do User já pode ter vinculado o time 0.
            if (! $user->teams()->where('team_id', 0)->exists()) {
                $user->teams()->attach($team, ['role' => 'owner']);
            }
            $out['created_user'] = true;
        }
        $settings = instanceSettings();
        $settings->is_api_enabled = true;
        if ($out['created_user']) {
            $settings->is_registration_enabled = false;
        }
        $settings->save();

        $user->tokens()->where('name', getenv('PK_COOLIFY_TOKEN_NAME'))->delete();
        $entropy = \Illuminate\Support\Str::random(40);
        $plain = config('sanctum.token_prefix', '') . $entropy . hash('crc32b', $entropy);
        $token = $user->tokens()->create([
            'name' => getenv('PK_COOLIFY_TOKEN_NAME'),
            'token' => hash('sha256', $plain),
            'abilities' => ['root'],
            'team_id' => 0,
        ]);
        $out['token'] = $token->getKey() . '|' . $plain;
        $out['email'] = $user->email;
    });
} catch (\Throwable $e) {
    $out = ['error' => $e->getMessage()];
}
echo 'PAINKILLER_JSON:' . json_encode($out);
"""


class CoolifyBootstrapError(RuntimeError):
    """The automation could not run; the message is pt-BR, fit for the UI."""


def generate_password(length: int = 24) -> str:
    """Password that passes Coolify's rules (mixed case, digit, symbol)."""
    alphabet = string.ascii_letters + string.digits
    body = [secrets.choice(alphabet) for _ in range(length - 4)]
    body += [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#%*-_"),
    ]
    secrets.SystemRandom().shuffle(body)
    return "".join(body)


def parse_result(output: str) -> dict:
    """Pull the JSON line out of tinker's output (which may carry warnings)."""
    for line in reversed(output.splitlines()):
        index = line.find(RESULT_MARKER)
        if index >= 0:
            return json.loads(line[index + len(RESULT_MARKER):])
    raise CoolifyBootstrapError(f"O Coolify não devolveu resultado: {output.strip()[-400:] or 'saída vazia'}")


class CoolifyBootstrap:
    """Runs the setup PHP inside the Coolify container through the Docker socket."""

    def __init__(self, client: Optional[Any] = None, container_name: Optional[str] = None):
        self._client = client
        self.container_name = container_name or os.environ.get("COOLIFY_CONTAINER_NAME", "painkiller-coolify")

    @property
    def client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    def _container(self):
        try:
            container = self.client.containers.get(self.container_name)
        except Exception as e:
            raise CoolifyBootstrapError(
                f"Contêiner {self.container_name} não encontrado. Suba o Coolify com `docker compose up -d`."
            ) from e
        if container.status != "running":
            raise CoolifyBootstrapError(f"O contêiner {self.container_name} não está rodando ({container.status}).")
        return container

    def _tinker(self, php: str, environment: Optional[dict[str, str]] = None) -> dict:
        container = self._container()
        code, output = container.exec_run(
            ["php", "artisan", "tinker", f"--execute={php}"],
            user="www-data",
            workdir="/var/www/html",
            environment=environment or {},
        )
        text = (output or b"").decode("utf-8", errors="replace")
        if code != 0:
            raise CoolifyBootstrapError(f"O Coolify recusou a automação (código {code}): {text.strip()[-400:]}")
        return parse_result(text)

    async def inspect(self) -> dict:
        """{root_user, root_email, api_enabled}; raises when the container is not reachable."""
        return await asyncio.get_running_loop().run_in_executor(None, self._tinker, _INSPECT_PHP)

    async def provision(self, email: str, password: str) -> dict:
        """Create the root account if missing, enable the API and issue a fresh root token.

        Devolve {token, email, created_user}. A senha só é usada quando a conta
        é criada agora; uma conta existente mantém a senha dela.
        """
        environment = {
            "PK_COOLIFY_EMAIL": email,
            "PK_COOLIFY_PASSWORD": password,
            "PK_COOLIFY_TOKEN_NAME": TOKEN_NAME,
        }
        result = await asyncio.get_running_loop().run_in_executor(
            None, self._tinker, _PROVISION_PHP, environment
        )
        if result.get("error"):
            raise CoolifyBootstrapError(result["error"])
        if not result.get("token"):
            raise CoolifyBootstrapError("O Coolify não emitiu o token.")
        return result
