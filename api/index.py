from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)  # Evita bloqueios de requisições cruzadas (CORS) entre frontend e backend

# Configurações de ambiente injetadas pelo painel da Vercel
VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")


def obter_conexao():
    """Retorna uma conexão limpa com o PostgreSQL usando dicionários para mapeamento."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def inicializar_infraestrutura_banco():
    """Cria a tabela relacional de produtos na inicialização caso ela não exista."""
    if not DATABASE_URL:
        print("Aviso: DATABASE_URL não localizada nas variáveis de ambiente.")
        return
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                id_produto VARCHAR(50) PRIMARY KEY,
                nome VARCHAR(255) NOT NULL,
                preco NUMERIC(10, 2) NOT NULL,
                categoria VARCHAR(100) NOT NULL,
                foto TEXT NOT NULL,
                visivel BOOLEAN DEFAULT TRUE
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("Infraestrutura do banco PostgreSQL verificada/criada com sucesso.")
    except Exception as e:
        print(f"Erro crítico na inicialização do banco: {str(e)}")


# Executa a checagem estrutural do banco de dados na subida do container serverless
inicializar_infraestrutura_banco()


# ======================================================================
# 1. CONTROLE DE AUTENTICAÇÃO DO ADMINISTRADOR
# ======================================================================
@app.route("/api/login", methods=["POST"])
@app.route("/login", methods=["POST"])
def login_admin():
    dados = request.get_json() or {}
    senha_enviada = dados.get("senha")

    if not senha_enviada:
        return jsonify({"authenticated": False, "error": "Senha não informada."}), 400

    if senha_enviada == ADMIN_PASSWORD:
        return jsonify({"authenticated": True, "token": "sessao_valida_lari_premium"}), 200
    else:
        return jsonify({"authenticated": False, "error": "Senha incorreta."}), 401


# ======================================================================
# 2. PROVEDOR DE ARMAZENAMENTO DE MÍDIA (VERCEL BLOB STORAGE)
# ======================================================================
@app.route("/api/upload", methods=["POST"])
@app.route("/upload", methods=["POST"])
def upload_foto():
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo de imagem enviado."}), 400

    file = request.files['foto']
    if file.filename == '':
        return jsonify({"error": "Nome de arquivo inválido."}), 400

    ext = os.path.splitext(file.filename)[1]
    nome_id = f"produto_{os.urandom(4).hex()}{ext}"
    conteudo_binario = file.read()

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token de gravação do Vercel Blob ausente."}), 500

    headers = {
        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
        "x-api-version": "1",
    }
    url_destino_blob = f"https://blob.vercel-storage.com/{nome_id}"

    try:
        resposta_vercel = requests.put(url_destino_blob, data=conteudo_binario, headers=headers)
        if resposta_vercel.status_code == 200:
            dados_retorno = resposta_vercel.json()
            return jsonify({"url": dados_retorno["url"]}), 200
        else:
            return jsonify({"error": f"Erro na API de borda da Vercel: {resposta_vercel.text}"}), 500
    except Exception as e:
        return jsonify({"error": f"Falha de comunicação interna de mídia: {str(e)}"}), 500


# ======================================================================
# 3. GESTÃO DOS REGISTROS DOS PRODUTOS (PERSISTÊNCIA RELACIONAL)
# ======================================================================
@app.route("/api/produtos", methods=["GET", "POST"])
@app.route("/produtos", methods=["GET", "POST"])
def gerenciar_produtos():
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        dados = request.get_json() or {}
        id_produto = dados.get("id_produto")
        nome = dados.get("nome")
        preco = dados.get("preco")
        categoria = dados.get("categoria")
        foto = dados.get("foto")
        visivel = dados.get("visivel", True)

        if not id_produto or not nome or preco is None:
            return jsonify({"error": "Metadados essenciais incompletos."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            # Mecanismo de UPSERT robusto para criação e atualização simultâneas
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) DO UPDATE 
                SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                    categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, visivel = EXCLUDED.visivel;
            """, (id_produto, nome, float(preco), categoria, foto, visivel))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"status": "success", "message": "Dados sincronizados no PostgreSQL."}), 201
        except Exception as e:
            return jsonify({"error": f"Falha operacional no banco Postgres: {str(e)}"}), 500

    # Processamento padrão de GET (Listagem pública da vitrine)
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM produtos;")
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

        # Saneamento de tipos numéricos para serialização estável em JSON
        for r in registros:
            r['preco'] = float(r['preco'])
        return jsonify(registros), 200
    except Exception as e:
        return jsonify({"error": f"Falha ao consultar acervo no banco: {str(e)}"}), 500


@app.route("/api/produtos/<id_prod>", methods=["DELETE"])
def remover_produto_banco(id_prod):
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (id_prod,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Registro removido com sucesso."}), 200
    except Exception as e:
        return jsonify({"error": f"Falha ao expurgar registro do banco: {str(e)}"}), 500


# ======================================================================
# 4. ROTA DE SEGURANÇA E ESCAPE (CATCH-ALL DA API)
# ======================================================================
@app.route("/api", defaults={"path": ""})
@app.route("/api/<path:path>")
def catch_all(path):
    return jsonify({
        "status": "API Premium ativa",
        "ambiente": "Vercel Serverless Edge Core",
        "gateway_route": path
    }), 200
