"""Paper-only positions. No broker client or order submission is used."""
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from .db import Contract, Security, Session
from .paper_db import PaperAccount, PaperFill, PaperPosition, PortfolioValuation
from .watchlist_api import latest_quote

router = APIRouter(prefix="/paper", tags=["paper portfolio"])

class AccountRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    initial_cash: float = Field(gt=0, le=100_000_000)

class OpenRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    request_id: UUID
    ticker: str = Field(min_length=1, max_length=12)
    symbol: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=10000)
    price: float = Field(gt=0, le=1_000_000)
    fee: float = Field(ge=0, le=1_000_000)

class CloseRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    request_id: UUID
    quantity: int = Field(ge=1, le=10000)
    price: float = Field(ge=0, le=1_000_000)
    fee: float = Field(ge=0, le=1_000_000)
    method: str = Field(pattern="^(sale|settlement)$")

def account_for_update(db):
    account = db.scalar(select(PaperAccount).where(PaperAccount.id == 1).with_for_update())
    if not account:
        raise HTTPException(409, "Create a paper account first.")
    return account

def fills_for(db, account_id):
    return db.scalars(select(PaperFill).join(PaperPosition).where(PaperPosition.account_id == account_id)).all()

def cash_balance(account, fills):
    return account.initial_cash + sum((-1 if f.side == "buy" else 1) * f.price * f.quantity * 100 - f.fee for f in fills)

def current_time():
    return datetime.now(timezone.utc)

def local_date():
    return current_time().astimezone(ZoneInfo("America/New_York")).date()

def serialize_position(db, position, fills):
    contract = db.get(Contract, position.contract_id)
    security = db.get(Security, contract.security_id)
    own = [f for f in fills if f.position_id == position.id]
    closes = [f for f in own if f.side in ("sale", "settlement")]
    closed_quantity = sum(f.quantity for f in closes)
    remaining = position.initial_quantity - closed_quantity
    realized = sum((f.price - position.entry_price) * f.quantity * 100 - f.fee - position.entry_fee * f.quantity / position.initial_quantity for f in closes)
    quote = latest_quote(db, contract) if remaining else None
    reasons = []
    mark = None
    if remaining:
        if local_date() > contract.expiration:
            reasons.append("Expired position: enter a hypothetical settlement; it is not automatically valued.")
        elif quote is None:
            reasons.append("No quote is available from the configured primary provider.")
        elif quote["stale"]:
            reasons.append("Quote is stale or its timestamp is missing; the position is unvalued.")
        elif quote["bid"] is None or quote["ask"] is None or quote["bid"] < 0 or quote["ask"] < quote["bid"]:
            reasons.append("A valid two-sided quote is unavailable; the position is unvalued.")
        elif quote["bid"] == 0:
            reasons.append("The bid is zero; no sale value is assumed.")
        else:
            mark = quote["bid"]
            if quote["feed"] == "indicative":
                reasons.append("Indicative mark is hypothetical and is not an executable price.")
    remaining_cost = (position.entry_price * 100 + position.entry_fee / position.initial_quantity) * remaining
    unrealized = (mark * 100 * remaining - remaining_cost) if mark is not None else None
    return {"id": position.id, "ticker": security.ticker, "symbol": contract.symbol, "kind": contract.kind,
        "strike": contract.strike, "expiration": contract.expiration, "opened_at": position.opened_at,
        "initial_quantity": position.initial_quantity, "remaining_quantity": remaining, "entry_price": position.entry_price,
        "entry_fee": position.entry_fee, "realized_profit": realized, "remaining_cost": remaining_cost,
        "mark_per_share": mark, "mark_value": mark * 100 * remaining if mark is not None else None,
        "unrealized_profit": unrealized, "quote": quote, "warnings": reasons,
        "fills": [{"side": f.side, "quantity": f.quantity, "price": f.price, "fee": f.fee, "occurred_at": f.occurred_at} for f in own]}

def portfolio(db, account):
    positions = db.scalars(select(PaperPosition).where(PaperPosition.account_id == account.id).order_by(PaperPosition.id.desc())).all()
    fills = fills_for(db, account.id)
    rows = [serialize_position(db, p, fills) for p in positions]
    cash = cash_balance(account, fills)
    open_rows = [p for p in rows if p["remaining_quantity"]]
    incomplete = any(p["mark_value"] is None for p in open_rows)
    equity = None if incomplete else cash + sum(p["mark_value"] for p in open_rows)
    complete = [p for p in rows if p["remaining_quantity"] == 0]
    win_rate = sum(p["realized_profit"] > 0 for p in complete) / len(complete) if complete else None
    closed_returns = [p["realized_profit"] / (p["entry_price"] * p["initial_quantity"] * 100 + p["entry_fee"]) for p in complete]
    saved_values = list(db.scalars(select(PortfolioValuation).where(PortfolioValuation.account_id == account.id).order_by(PortfolioValuation.id.desc()).limit(100)))
    sampled_drawdown = None
    if len(saved_values) >= 2 and all(v.equity is not None and v.equity > 0 for v in saved_values):
        peak = saved_values[-1].equity
        sampled_drawdown = 0.0
        for point in reversed(saved_values):
            peak = max(peak, point.equity)
            sampled_drawdown = min(sampled_drawdown, point.equity / peak - 1)
    return {"initial_cash": account.initial_cash, "cash": cash, "equity": equity,
        "sampled_max_drawdown": sampled_drawdown, "sampled_valuation_count": len(saved_values),
        "total_return": (equity - account.initial_cash) / account.initial_cash if equity is not None else None,
        "realized_profit": sum(p["realized_profit"] for p in rows), "closed_positions": len(complete),
        "win_rate": win_rate, "average_closed_return": sum(closed_returns) / len(closed_returns) if closed_returns else None,
        "incomplete_marks": sum(p["mark_value"] is None for p in open_rows), "positions": rows,
        "benchmark": {"status": "unavailable", "reason": "A time-aligned, dividend-adjusted benchmark and portfolio valuation history are not available."},
        "note": "Paper only. Manual hypothetical fills; no orders are sent. Indicative marks are not executable."}

@router.get("")
def get_portfolio():
    with Session() as db:
        account = db.get(PaperAccount, 1)
        return portfolio(db, account) if account else {"configured": False, "positions": []}

@router.post("/account", status_code=201)
def create_account(request: AccountRequest):
    with Session.begin() as db:
        if db.get(PaperAccount, 1):
            raise HTTPException(409, "Paper account already exists.")
        account = PaperAccount(id=1, initial_cash=request.initial_cash)
        db.add(account)
        db.flush()
        return portfolio(db, account)

@router.post("/positions", status_code=201)
def open_position(request: OpenRequest):
    with Session.begin() as db:
        account = account_for_update(db)
        previous = db.scalar(select(PaperFill).where(PaperFill.request_id == str(request.request_id)))
        if previous:
            p = db.get(PaperPosition, previous.position_id)
            c = db.get(Contract, p.contract_id)
            sec = db.get(Security, c.security_id)
            if previous.side != "buy" or sec.ticker != request.ticker.upper() or c.symbol != request.symbol or previous.quantity != request.quantity or previous.price != request.price or previous.fee != request.fee:
                raise HTTPException(409, "Request ID was already used for a different fill.")
            return serialize_position(db, p, fills_for(db, account.id))
        contract = db.scalar(select(Contract).join(Security).where(Security.ticker == request.ticker.upper(), Contract.symbol == request.symbol))
        if not contract:
            raise HTTPException(404, "Option contract not found for that ticker.")
        if contract.expiration < local_date():
            raise HTTPException(422, "Cannot open a paper position after expiration.")
        debit = request.quantity * request.price * 100 + request.fee
        if debit > cash_balance(account, fills_for(db, account.id)) + 1e-8:
            raise HTTPException(422, "Not enough hypothetical cash.")
        position = PaperPosition(account_id=account.id, contract_id=contract.id, initial_quantity=request.quantity, entry_price=request.price, entry_fee=request.fee)
        db.add(position)
        db.flush()
        db.add(PaperFill(position_id=position.id, request_id=str(request.request_id), side="buy", quantity=request.quantity, price=request.price, fee=request.fee))
        db.flush()
        return serialize_position(db, position, fills_for(db, account.id))

@router.post("/positions/{position_id}/close")
def close_position(position_id: int, request: CloseRequest):
    with Session.begin() as db:
        account = account_for_update(db)
        position = db.scalar(select(PaperPosition).where(PaperPosition.id == position_id, PaperPosition.account_id == account.id).with_for_update())
        if not position:
            raise HTTPException(404, "Paper position not found.")
        previous = db.scalar(select(PaperFill).where(PaperFill.request_id == str(request.request_id)))
        if previous:
            if previous.position_id != position_id or previous.side != request.method or previous.quantity != request.quantity or previous.price != request.price or previous.fee != request.fee:
                raise HTTPException(409, "Request ID was already used for a different fill.")
            return serialize_position(db, position, fills_for(db, account.id))
        contract = db.get(Contract, position.contract_id)
        today = local_date()
        if request.method == "sale" and today > contract.expiration:
            raise HTTPException(422, "An expired option requires a manually entered paper settlement, not a sale.")
        if request.method == "settlement" and today < contract.expiration:
            raise HTTPException(422, "Paper settlement can be entered on or after expiration.")
        fills = fills_for(db, account.id)
        current = serialize_position(db, position, fills)
        if request.quantity > current["remaining_quantity"]:
            raise HTTPException(422, "Cannot close more contracts than remain open.")
        db.add(PaperFill(position_id=position.id, request_id=str(request.request_id), side=request.method, quantity=request.quantity, price=request.price, fee=request.fee))
        db.flush()
        return serialize_position(db, position, fills_for(db, account.id))

@router.post("/valuations", status_code=201)
def save_valuation():
    with Session.begin() as db:
        account = account_for_update(db)
        snapshot = portfolio(db, account)
        valuation = PortfolioValuation(account_id=account.id, cash=snapshot["cash"], equity=snapshot["equity"], details=jsonable_encoder(snapshot))
        db.add(valuation)
        db.flush()
        return {"id": valuation.id, "observed_at": valuation.observed_at, "cash": valuation.cash, "equity": valuation.equity, "details": valuation.details}

@router.get("/valuations")
def valuation_history():
    with Session() as db:
        account = db.get(PaperAccount, 1)
        if not account:
            return []
        rows = db.scalars(select(PortfolioValuation).where(PortfolioValuation.account_id == account.id).order_by(PortfolioValuation.id.desc()).limit(100))
        return [{"id": row.id, "observed_at": row.observed_at, "cash": row.cash, "equity": row.equity, "details": row.details} for row in rows]
