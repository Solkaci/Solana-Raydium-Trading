
import asyncio
import os
import time
from solana.transaction import Transaction
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.system_program import TransferParams, transfer
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from jito_searcher_client import get_async_searcher_client
from jito_searcher_client.convert import versioned_tx_to_protobuf_packet
from jito_searcher_client.generated.bundle_pb2 import Bundle
from jito_searcher_client.generated.searcher_pb2 import NextScheduledLeaderRequest, NextScheduledLeaderResponse, SendBundleRequest
from dotenv import load_dotenv
from solana.rpc.api import Client

load_dotenv()
payer = Keypair.from_base58_string(os.getenv('PrivateKey'))
RPC_HTTPS_URL = os.getenv("RPC_HTTPS_URL")
solana_client = Client(RPC_HTTPS_URL)
async_solana_client = AsyncClient(RPC_HTTPS_URL)
LAMPORTS_PER_SOL = 1000000000

Wallet_to_receive = Pubkey.from_string("777cz6dNUWu4hGNKda7gmnnqTz1RUxB2BGpP3S9ky466")  # Enter Wallet to receive SOL
params = TransferParams(
    from_pubkey=payer.pubkey(),
    to_pubkey=Wallet_to_receive,
    lamports=int(0.0005 * 10**9)  # Amount of SOL to transfer
)

transaction = Transaction()
transaction.add(transfer(params))
transaction.sign(payer)


async def send_and_confirm_transaction(client, transaction, payer, max_attempts=3):
    attempts = 0
    while attempts < max_attempts:
        try:
            ### SENDING THROUGH JITO
            print("Sending Through Jito")

            jito_payer = Keypair.from_base58_string(os.getenv("JITO_PAYER"))
            BLOCK_ENGINE_URL = "frankfurt.mainnet.block-engine.jito.wtf"
            jito_client = await get_async_searcher_client(BLOCK_ENGINE_URL, jito_payer)

            txs = []
            tip_account_pubkey = Pubkey.from_string(os.getenv("TIP_ACCOUNT"))

            is_leader_slot = False
            print("waiting for jito leader...")
            while not is_leader_slot:
                time.sleep(0.5)
                next_leader: NextScheduledLeaderResponse = await jito_client.GetNextScheduledLeader(
                    NextScheduledLeaderRequest())
                num_slots_to_leader = next_leader.next_leader_slot - next_leader.current_slot
                print(f"waiting {num_slots_to_leader} slots to jito leader")
                is_leader_slot = num_slots_to_leader <= 5

            ix = transfer(
                TransferParams(
                    from_pubkey=payer.pubkey(), to_pubkey=tip_account_pubkey,
                    lamports=int(0.000020002 * LAMPORTS_PER_SOL)  # TIP AMOUNT
                )
            )


            block_hash = solana_client.get_latest_blockhash(commitment=Confirmed)

            print(block_hash.value.blockhash)


            msg = MessageV0.try_compile(
                payer=payer.pubkey(),
                instructions=[transaction.instructions[0],ix],
                address_lookup_table_accounts=[],
                recent_blockhash=block_hash.value.blockhash,
            )

            tx1 = VersionedTransaction(msg, [payer])

            txs.append(tx1)

            packets = [versioned_tx_to_protobuf_packet(tx) for tx in txs]
            uuid_response = await jito_client.SendBundle(SendBundleRequest(bundle=Bundle(header=None, packets=packets)))

            print(f"bundle uuid: {uuid_response.uuid}")
            block_height = solana_client.get_block_height(Confirmed).value
            print(f"Block height: {block_height}")

            for tx in txs:
                confirmation_resp = await async_solana_client.confirm_transaction(

                    tx.signatures[0],
                    commitment=Confirmed,
                    sleep_seconds=0.5,
                    last_valid_block_height=block_height + 15
                )
                print(f"Confirmation Response: {confirmation_resp.value}")

                if confirmation_resp.value[0].err is None and str(
                        confirmation_resp.value[0].confirmation_status) == "TransactionConfirmationStatus.Confirmed":
                    print("Transaction Confirmed")
                    print(f"Transaction Signature: https://solscan.io/tx/{tx.signatures[0]}")
                    return

            attempts += 1
            print("Transaction not confirmed, retrying...")
        except Exception as e:
            print(f"Attempt {attempts}: Exception occurred - {e}")
            attempts += 1

    if attempts == max_attempts:
        print("Maximum attempts reached. Transaction could not be confirmed.")

asyncio.run(send_and_confirm_transaction(solana_client, transaction, payer))
