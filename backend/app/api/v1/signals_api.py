from fastapi import APIRouter


router=APIRouter(
prefix="/signals"
)



@router.get("/{symbol}")
def get_signal(symbol:str):


    return {

     "symbol":symbol,

     "signal":"WAIT",

     "confidence":80
    }
