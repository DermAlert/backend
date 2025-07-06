import random
import os
import requests
import asyncio
import aiohttp
import json
import tempfile
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from app.database.database import SessionLocal 
from ..core.security import get_password_hash
from ..utils.minio import upload_to_minio, get_minio_client, upload_file_to_minio
from faker import Faker
from typing import List, Dict

# Importe os modelos definidos (User, Role, UnidadeSaude, Paciente, Atendimento, TermoConsentimento,
# SaudeGeral, AvaliacaoFototipo, RegistroLesoes, RegistroLesoesImagens, LocalLesao)
from .models import (
    User,
    Role,
    UnidadeSaude,
    Paciente,
    Atendimento,
    TermoConsentimento,
    SaudeGeral,
    AvaliacaoFototipo,
    HistoricoCancerPele,
    FatoresRiscoProtecao,
    InvestigacaoLesoesSuspeitas,
    RegistroLesoes,
    RegistroLesoesImagens,
    LocalLesao,
)

# Função auxiliar para truncar strings de forma segura
def safe_truncate(value, max_length):
    """Trunca uma string para o tamanho máximo especificado."""
    if value is None:
        return None
    return str(value)[:max_length]

# Lista de possíveis locais para as lesões
LESOES_LOCAIS = ["Face", "Braço", "Perna", "Tronco", "Mão", "Pé"]

# URLs de imagens fake para termos de consentimento (documentos fictícios)
FAKE_DOCUMENT_URLS = [
    "https://picsum.photos/800/600?random=1",
    "https://picsum.photos/800/600?random=2", 
    "https://picsum.photos/800/600?random=3",
    "https://picsum.photos/800/600?random=4",
    "https://picsum.photos/800/600?random=5"
]

# Cache para imagens ISIC baixadas
ISIC_IMAGES_CACHE = []

async def fetch_isic_images(session_http: aiohttp.ClientSession, limit: int = 50) -> List[Dict]:
    """Busca imagens da API ISIC."""
    try:
        url = f"https://api.isic-archive.com/api/v2/images/?limit={limit}"
        headers = {
            'accept': 'application/json',
            'X-CSRFToken': 'enCb5d3t566IR1Aj04WvUTcvAxOyGCcl8ynDbWuclXD2Bpg3N6mXuefQPkPizYSx'
        }
        
        async with session_http.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('results', [])
            else:
                print(f"Erro ao buscar imagens ISIC: {response.status}")
                return []
    except Exception as e:
        print(f"Erro na requisição ISIC: {e}")
        return []

async def download_and_upload_image(session_http: aiohttp.ClientSession, image_url: str, object_name: str) -> str:
    """Baixa uma imagem e faz upload para o MinIO."""
    try:
        async with session_http.get(image_url) as response:
            if response.status == 200:
                image_data = await response.read()
                
                # Cria arquivo temporário
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                    temp_file.write(image_data)
                    temp_file_path = temp_file.name
                
                try:
                    # Upload para MinIO usando a função síncrona
                    upload_result = upload_file_to_minio(temp_file_path, object_name, "image/jpeg")
                    return upload_result
                finally:
                    # Remove arquivo temporário
                    os.unlink(temp_file_path)
            else:
                print(f"Erro ao baixar imagem: {response.status}")
                return None
    except Exception as e:
        print(f"Erro no download/upload da imagem: {e}")
        return None

# Função auxiliar para gerar datas de nascimento aleatórias (entre 1950 e 2010)
def random_birthdate():
    start_date = date(1950, 1, 1)
    end_date = date(2010, 12, 31)
    delta = end_date - start_date
    random_days = random.randrange(delta.days)
    return start_date + timedelta(days=random_days)

# Função auxiliar para gerar valores válidos para AvaliacaoFototipo
def random_avaliacao_fototipo():
    return AvaliacaoFototipo(
        cor_pele=random.choice([0, 2, 4, 8, 12, 16, 20]),
        cor_olhos=random.choice([0, 1, 2, 3, 4]),
        cor_cabelo=random.choice([0, 1, 2, 3, 4]),
        quantidade_sardas=random.choice([0, 1, 2, 3]),
        reacao_sol=random.choice([0, 2, 4, 6, 8]),
        bronzeamento=random.choice([0, 2, 4, 6]),
        sensibilidade_solar=random.choice([0, 1, 2, 3, 4]),
    )

# Função auxiliar para gerar um registro de saúde geral
def random_saude_geral():
    return SaudeGeral(
        doencas_cronicas=random.choice([True, False]),
        hipertenso=random.choice([True, False]),
        diabetes=random.choice([True, False]),
        cardiopatia=random.choice([True, False]),
        outras_doencas="Hipertensão leve" if random.choice([True, False]) else None,
        diagnostico_cancer=random.choice([True, False]),
        tipo_cancer="Carcinoma basocelular" if random.choice([True, False]) else None,
        uso_medicamentos=random.choice([True, False]),
        medicamentos="Losartana 50mg" if random.choice([True, False]) else None,
        possui_alergia=random.choice([True, False]),
        alergias="Pólen" if random.choice([True, False]) else None,
        ciruturgias_dermatologicas=random.choice([True, False]),
        tipo_procedimento="Peeling químico" if random.choice([True, False]) else None,
        pratica_atividade_fisica=random.choice([True, False]),
        frequencia_atividade_fisica=random.choice(["Diária", "Frequente", "Moderada", "Ocasional"]),
    )


async def populate_db():
    # Inicia sessão HTTP para downloads com timeout
    timeout = aiohttp.ClientTimeout(total=30)  # 30 segundos de timeout
    async with aiohttp.ClientSession(timeout=timeout) as session_http:
        async with SessionLocal() as session:

            # Busca imagens ISIC no início para cache
            print("Buscando imagens da API ISIC...")
            global ISIC_IMAGES_CACHE
            ISIC_IMAGES_CACHE = await fetch_isic_images(session_http, limit=100)
            print(f"Cache de {len(ISIC_IMAGES_CACHE)} imagens ISIC carregado.")

            # 1. Criação das unidades de saúde
            unidade1 = UnidadeSaude(
                nome_unidade_saude="Unidade de Saúde Central",
                nome_localizacao="Rua das Flores, 123 - Centro, São Paulo",
                codigo_unidade_saude="USC001",
                cidade_unidade_saude="São Paulo",
                fl_ativo=True
            )
            unidade2 = UnidadeSaude(
                nome_unidade_saude="Posto de Saúde do Norte",
                nome_localizacao="Avenida Brasil, 456 - Bairro Alto, Rio de Janeiro",
                codigo_unidade_saude="PSN002",
                cidade_unidade_saude="Rio de Janeiro",
                fl_ativo=True
            )
            unidade3 = UnidadeSaude(
                nome_unidade_saude="Clínica Vida",
                nome_localizacao="Travessa das Acácias, 789 - Zona Sul, Belo Horizonte",
                codigo_unidade_saude="CV003",
                cidade_unidade_saude="Belo Horizonte",
                fl_ativo=True
            )
            session.add_all([unidade1, unidade2, unidade3])
            await session.commit()  # Para garantir que as unidades tenham um id

            # 2. Criação dos papéis (roles)
            role_admin = Role(name="Admin", nivel_acesso=1)
            role_supervisor = Role(name="Supervisor", nivel_acesso=2)
            role_pesquisador = Role(name="Pesquisador", nivel_acesso=3)
            session.add_all([role_admin, role_supervisor, role_pesquisador])
            await session.commit()  # Para garantir que os roles tenham um id

            # 3. Criação de usuários (pelo menos 5) e associação com uma unidade de saúde
            # Observação: cada usuário pode ter mais de um papel, mas neste exemplo cada um terá apenas 1.
            usuario1 = User(
                nome_usuario="admin_brasil",
                email="admin@exemplo.com",
                cpf="11111111111",
                senha_hash=get_password_hash("admin123"),
                fl_ativo=True,
                roles=[role_admin],
                unidadeSaude=[unidade1]
            )
            usuario2 = User(
                nome_usuario="supervisor_rj",
                email="sup.rj@exemplo.com",
                cpf="22222222222",
                senha_hash=get_password_hash("supervisor123"),
                fl_ativo=True,
                roles=[role_supervisor],
                unidadeSaude=[unidade2]
            )
            usuario3 = User(
                nome_usuario="pesq_sp",
                email="pesq.sp@exemplo.com",
                cpf="33333333333",
                senha_hash=get_password_hash("pesquisador123"),
                fl_ativo=True,
                roles=[role_pesquisador],
                unidadeSaude=[unidade1]
            )
            usuario4 = User(
                nome_usuario="pesq_bh",
                email="pesq.bh@exemplo.com",
                cpf="44444444444",
                senha_hash=get_password_hash("pesquisador123"),
                fl_ativo=True,
                roles=[role_pesquisador],
                unidadeSaude=[unidade3]
            )
            usuario5 = User(
                nome_usuario="supervisor_bh",
                email="sup.bh@exemplo.com",
                cpf="55555555555",
                senha_hash=get_password_hash("supervisor123"),
                fl_ativo=True,
                roles=[role_supervisor],
                unidadeSaude=[unidade3]
            )
            session.add_all([usuario1, usuario2, usuario3, usuario4, usuario5])
            await session.commit()

            usuarios = [usuario1, usuario2, usuario3, usuario4, usuario5]

            # 3. Criação dos locais de lesão
            novos_locais = [
                LocalLesao(nome="Cabeça"),
                LocalLesao(nome="Face"),
                LocalLesao(nome="Pescoço"),
                LocalLesao(nome="Ombro direito"),
                LocalLesao(nome="Ombro esquerdo"),
                LocalLesao(nome="Braço direito"),
                LocalLesao(nome="Braço esquerdo"),
                LocalLesao(nome="Cotovelo direito"),
                LocalLesao(nome="Cotovelo esquerdo"),
                LocalLesao(nome="Antebraço direito"),
                LocalLesao(nome="Antebraço esquerdo"),
                LocalLesao(nome="Punho direito"),
                LocalLesao(nome="Punho esquerdo"),
                LocalLesao(nome="Mão direita"),
                LocalLesao(nome="Mão esquerda"),
                LocalLesao(nome="Tórax"),
                LocalLesao(nome="Abdômen"),
                LocalLesao(nome="Lombar"),
                LocalLesao(nome="Pélvis"),
                LocalLesao(nome="Quadril direito"),
                LocalLesao(nome="Quadril esquerdo"),
                LocalLesao(nome="Coxa direita"),
                LocalLesao(nome="Coxa esquerda"),
                LocalLesao(nome="Joelho direito"),
                LocalLesao(nome="Joelho esquerdo"),
                LocalLesao(nome="Perna direita"),
                LocalLesao(nome="Perna esquerda"),
                LocalLesao(nome="Tornozelo direito"),
                LocalLesao(nome="Tornozelo esquerdo"),
                LocalLesao(nome="Pé direito"),
                LocalLesao(nome="Pé esquerdo")
            ]

            session.add_all(novos_locais)
            await session.commit()  # Insere os locais na tabela

            # Recupera os locais para uso na criação dos registros de lesão
            result = await session.execute(select(LocalLesao))
            locais_lesao = result.scalars().all()
            local_lesao_index = 0

            # Inicializa o Faker para gerar dados realistas
            fake = Faker('pt_BR')
            
            # Gera nomes de pacientes usando Faker
            nomes_pacientes = [fake.name() for _ in range(100)]
            # Supondo que os usuários já foram criados e estão disponíveis
            result = await session.execute(select(User))
            usuarios = result.scalars().all()

            from datetime import date
            import random

            print(f"Criando {len(nomes_pacientes)} pacientes...")
            
            for i in range(len(nomes_pacientes)):
                if i % 10 == 0:  # Progresso a cada 10 pacientes para feedback mais frequente
                    print(f"Criado paciente {i+1}/{len(nomes_pacientes)}")
                
                # Cria um paciente com dados mais realistas
                paciente = Paciente(
                    nome_paciente=safe_truncate(nomes_pacientes[i], 100),  # Limita nome para 100 caracteres
                    data_nascimento=random_birthdate(),  # Usa função para gerar data aleatória
                    sexo=random.choice(["M", "F", "NB", "NR", "O"]),
                    sexo_outro="",
                    cpf_paciente=f"{10000000000 + i:011d}",  # CPF sequencial para evitar duplicatas e garantir 11 dígitos
                    num_cartao_sus=f"{100000000000000 + i}",
                    endereco_paciente=safe_truncate(fake.address(), 300),  # Limita endereço para 300 caracteres
                    telefone_paciente=f"{11000000000 + i:011d}",  # Telefone sequencial para garantir 11 dígitos
                    email_paciente=safe_truncate(fake.email(), 100),  # Limita email para 100 caracteres
                    autoriza_pesquisa=random.choice([True, False])
                )
                session.add(paciente)
                await session.commit()  # Para obter o id do paciente

                # Seleciona um usuário para o atendimento (de forma cíclica)
                usuario_atendimento = usuarios[i % len(usuarios)]

                # Cria um TermoConsentimento com imagem fake baixada
                termo_path = f"termos/consentimento_{i}_fallback.jpg"  # Path padrão
                
                try:
                    fake_doc_url = random.choice(FAKE_DOCUMENT_URLS)
                    termo_object_name = f"termos/consentimento_{i}_{fake.uuid4()}.jpg"
                    
                    # Tenta baixar e fazer upload da imagem fake do termo
                    downloaded_path = await download_and_upload_image(session_http, fake_doc_url, termo_object_name)
                    if downloaded_path:
                        termo_path = downloaded_path
                except Exception as e:
                    print(f"Erro ao baixar termo para paciente {i}: {e}")
                
                termo = TermoConsentimento(
                    arquivo_path=safe_truncate(termo_path, 300)
                )
                session.add(termo)
                await session.commit()

                # Cria um objeto SaudeGeral com dados fictícios mais variados
                saude_geral = random_saude_geral()  # Usa função para gerar dados aleatórios
                session.add(saude_geral)
                await session.commit()

                # Cria um objeto AvaliacaoFototipo com valores válidos conforme as restrições
                avaliacao_fototipo = random_avaliacao_fototipo()  # Usa função para gerar dados aleatórios
                session.add(avaliacao_fototipo)
                await session.commit()

                
                # Cria um objeto HistoricoCancerPele com valores fictícios
                tem_historico_familiar = random.choice([True, False])
                historico_cancer_pele = HistoricoCancerPele(
                    historico_familiar=tem_historico_familiar,
                    grau_parentesco=random.choice(['Pai', 'Mãe', 'Avô/Avó', 'Irmão/Irmã', 'Outro']) if tem_historico_familiar else None,
                    tipo_cancer_familiar=random.choice(['Melanoma', 'Carcinoma Basocelular', 'Carcinoma Espinocelular', 'Outro']) if tem_historico_familiar else None,
                    tipo_cancer_familiar_outro="Cancer de pele raro" if tem_historico_familiar and random.choice([True, False]) else None,
                    
                    diagnostico_pessoal=random.choice([True, False]),
                    tipo_cancer_pessoal=random.choice(['Melanoma', 'Carcinoma Basocelular', 'Carcinoma Espinocelular', 'Outro']) if random.choice([True, False]) else None,
                    tipo_cancer_pessoal_outro=None,
                    
                    lesoes_precancerigenas=random.choice([True, False]),
                    tratamento_lesoes=random.choice([True, False]),
                    tipo_tratamento=random.choice(['Cirurgia', 'Crioterapia', 'Radioterapia', 'Outro']) if random.choice([True, False]) else None,
                    tipo_tratamento_outro=None
                )
                session.add(historico_cancer_pele)
                await session.commit()
                
                # Cria um objeto FatoresRiscoProtecao com valores fictícios
                exposicao_solar = random.choice([True, False])
                fatores_risco_protecao = FatoresRiscoProtecao(
                    exposicao_solar_prolongada=exposicao_solar,
                    frequencia_exposicao_solar=random.choice(['Diariamente', 'Algumas vezes por semana', 'Ocasionalmente']) if exposicao_solar else None,
                    
                    queimaduras_graves=random.choice([True, False]),
                    quantidade_queimaduras=random.choice(['1-2', '3-5', 'Mais de 5']) if random.choice([True, False]) else None,
                    
                    uso_protetor_solar=random.choice([True, False]),
                    fator_protecao_solar=random.choice(['15', '30', '50', '70', '100 ou mais']) if random.choice([True, False]) else None,
                    
                    uso_chapeu_roupa_protecao=random.choice([True, False]),
                    
                    bronzeamento_artificial=random.choice([True, False]),
                    
                    checkups_dermatologicos=random.choice([True, False]),
                    frequencia_checkups=random.choice(['Anualmente', 'A cada 6 meses', 'Outro']) if random.choice([True, False]) else None,
                    frequencia_checkups_outro=None,
                    
                    participacao_campanhas_prevencao=random.choice([True, False])
                )
                session.add(fatores_risco_protecao)
                await session.commit()
                
                # Cria um objeto InvestigacaoLesoesSuspeitas com valores fictícios
                investigacao_lesoes = InvestigacaoLesoesSuspeitas(
                    mudanca_pintas_manchas=random.choice([True, False]),
                    sintomas_lesoes=random.choice([True, False]),
                    
                    tempo_alteracoes=random.choice(['Menos de 1 mês', '1-3 meses', '3-6 meses', 'Mais de 6 meses']) if random.choice([True, False]) else None,
                    
                    caracteristicas_lesoes=random.choice([True, False]),
                    
                    consulta_medica=random.choice([True, False]),
                    diagnostico_lesoes="Lesão benigna, apenas monitoramento recomendado" if random.choice([True, False]) else None
                )
                session.add(investigacao_lesoes)
                await session.commit()



                # Cria o atendimento relacionando os objetos acima
                atendimento = Atendimento(
                    paciente_id=paciente.id,
                    user_id=usuario_atendimento.id,
                    termo_consentimento_id=termo.id,
                    saude_geral_id=saude_geral.id,
                    avaliacao_fototipo_id=avaliacao_fototipo.id,
                    unidade_saude_id=usuario_atendimento.unidadeSaude[0].id
                )
                session.add(atendimento)
                await session.commit()

                # Para cada paciente, cria entre 0 e 3 registros de lesões (reduzido para acelerar)
                num_lesoes = random.randint(0, 3)  # Reduzido de 5 para 3 para acelerar
                for j in range(num_lesoes):
                    # Seleciona um local para a lesão garantindo variedade
                    local = random.choice(locais_lesao)  # Escolhe local aleatório
                    
                    registro_lesao = RegistroLesoes(
                        local_lesao_id=local.id,
                        descricao_lesao=safe_truncate(f"Lesão observada na região {local.nome} - {fake.text(max_nb_chars=200)}", 500),
                        atendimento_id=atendimento.id
                    )
                    session.add(registro_lesao)
                    await session.commit()

                    # Cria entre 1 e 2 imagens por lesão (reduzido para acelerar)
                    num_imagens = random.randint(1, 2)  # Reduzido de 3 para 2
                    for k in range(num_imagens):
                        # Path padrão em caso de falha
                        image_path = f"imagens/lesao_{i}_{j+1}_{k+1}_fallback.jpg"
                        
                        try:
                            # Seleciona uma imagem aleatória do cache ISIC
                            if ISIC_IMAGES_CACHE:
                                isic_image = random.choice(ISIC_IMAGES_CACHE)
                                thumbnail_url = isic_image.get('files', {}).get('thumbnail_256', {}).get('url', '')
                                isic_id = isic_image.get('isic_id', f'unknown_{k}')
                                
                                if thumbnail_url:
                                    # Nome do objeto no MinIO
                                    image_object_name = f"imagens/lesao_{i}_{j+1}_{k+1}_{isic_id}.jpg"
                                    
                                    # Tenta baixar e fazer upload da imagem real
                                    downloaded_path = await download_and_upload_image(session_http, thumbnail_url, image_object_name)
                                    if downloaded_path:
                                        image_path = downloaded_path
                        except Exception as e:
                            print(f"Erro ao baixar imagem de lesão para paciente {i}: {e}")
                        
                        imagem = RegistroLesoesImagens(
                            arquivo_path=safe_truncate(image_path, 300),
                            registro_lesoes_id=registro_lesao.id
                        )
                        session.add(imagem)
                        await session.commit()
                        
            print(f"Criação de {len(nomes_pacientes)} pacientes concluída!")
            print("Upload de imagens reais da API ISIC e documentos fake concluído!")
                