from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

# =====================================================================
# CONFIGURAÇÕES DE AMBIENTE (Painel Vercel)
# =====================================================================
VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSOWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL_NON_POOLING")

# =====================================================================
# INFRAESTRUTURA DE BANCO DE DADOS (PostgreSQL)
# =====================================================================
def obter_conexao():
    if not DATABASE_URL:
        raise ValueError("A string de conexão (POSTGRES_URL) não foi configurada na Vercel.")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=5)
    conn.autocommit = True
    return conn

def inicializar_infraestrutura_banco():
    if DATABASE_URL:
        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS produtos (
                    id_produto VARCHAR(255) PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    preco NUMERIC(10, 2) NOT NULL,
                    categoria VARCHAR(100) NOT NULL,
                    foto TEXT NOT NULL,
                    visivel BOOLEAN DEFAULT TRUE
                );
            """)
            cursor.close()
            conn.close()
            print("Estrutura do banco de dados verificada/criada com sucesso.")
        except Exception as e:
            print(f"Aviso: Erro ao inicializar tabelas do banco: {str(e)}")

# Inicialização segura do banco
try:
    inicializar_infraestrutura_banco()
except Exception as e:
    print(f"Falha na rotina global de banco: {str(e)}")

# =====================================================================
# ROTA: Autenticação Administrativa
# =====================================================================
@app.route('/api/admin/login', methods=['POST'])
def efetuar_login_administrativo():
    dados = request.get_json() or {}
    senha_digitada = str(dados.get('senha', '')).strip()

    # Puxa ADMIN_PASSWORD da Vercel. Se não existir, usa 'admin123' como fallback
    senha_mestra = os.environ.get("ADMIN_PASSWORD")

    if senha_digitada == senha_mestra:
        # Retorna o mesmo token seguro esperado pelo seu ecossistema
        return jsonify({
            "auth": True,
            "token": "Bearer sessao_valida_lari_premium"
        }), 200
    else:
        return jsonify({"erro": "Senha incorreta"}), 401

# =====================================================================
# ROTA: Upload de Imagens (Vercel Blob Storage)
# =====================================================================
@app.route("/api/upload", methods=["POST"])
@app.route("/upload", methods=["POST"])
def processar_upload_imagem():
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo de imagem foi enviado."}), 400

    arquivo_foto = request.files['foto']
    if arquivo_foto.filename == '':
        return jsonify({"error": "Nome de arquivo inválido."}), 400

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token do Vercel Blob não configurado no servidor."}), 500

    try:
        nome_limpo_arquivo = arquivo_foto.filename.replace(" ", "_")
        url_blob = f"https://blob.vercel-storage.com/{nome_limpo_arquivo}"

        headers_blob = {
            "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
            "x-api-version": "2023-01-01"
        }

        conteudo_arquivo = arquivo_foto.read()
        resposta_blob = requests.put(url_blob, data=conteudo_arquivo, headers=headers_blob)

        if resposta_blob.status_code in [200, 201]:
            dados_retorno = resposta_blob.json()
            return jsonify({"url": dados_retorno.get("url")}), 200

        return jsonify({"error": f"Erro na API do Storage: {resposta_blob.text}"}), 500

    except Exception as e:
        return jsonify({"error": f"Exceção no upload: {str(e)}"}), 500

# =====================================================================
# ROTAS: Operações do Catálogo (Listagem e Cadastro)
# =====================================================================
@app.route("/api/produtos", methods=["GET", "POST"])
@app.route("/produtos", methods=["GET", "POST"])
def gerenciar_colecao_produtos():
    # OPERAÇÃO: Cadastrar ou Atualizar Produto
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        dados_produto = request.get_json() or {}
        id_produto = dados_produto.get("id_produto")
        nome = dados_produto.get("nome")
        preco = dados_produto.get("preco")
        categoria = dados_produto.get("categoria")
        foto = dados_produto.get("foto")
        visivel = dados_produto.get("visivel", True)

        if not id_produto or not nome or preco is None or not categoria or not foto:
            return jsonify({"error": "Preencha todos os campos obrigatórios."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) DO UPDATE 
                SET nome = EXCLUDED.nome,
                    preco = EXCLUDED.preco,
                    categoria = EXCLUDED.categoria,
                    foto = EXCLUDED.foto,
                    visivel = EXCLUDED.visivel;
            """, (str(id_produto).strip(), nome, float(preco), categoria, foto, bool(visivel)))
            cursor.close()
            conn.close()
            return jsonify({"status": "success"}), 201
        except Exception as e:
            return jsonify({"error": f"Erro ao salvar no banco: {str(e)}"}), 500

    # OPERAÇÃO: Listar todos os produtos (GET)
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT id_produto, nome, preco, categoria, foto, visivel FROM produtos ORDER BY nome ASC;")
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

        for r in registros:
            r['preco'] = float(r['preco'])

        return jsonify(registros), 200
    except Exception as e:
        return jsonify({"error": f"Erro ao consultar catálogo: {str(e)}"}), 500

# =====================================================================
# ROTA: Remoção de Produto por ID
# =====================================================================
@app.route("/api/produtos/<path:id_prod>", methods=["DELETE"])
@app.route("/produtos/<path:id_prod>", methods=["DELETE"])
def remover_produto_banco(id_prod):
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    id_limpo = str(id_prod).strip()

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (id_limpo,))
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Produto excluído com sucesso."}), 200
    except Exception as e:
        return jsonify({"error": f"Erro ao remover produto: {str(e)}"}), 500

# =====================================================================
# FALLBACK: Rota residual para evitar quebras de roteamento
# =====================================================================
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    return jsonify({
        "status": "online",
        "message": "API LariAcessórios ativa.",
        "path": f"/{path}"
    }), 200
