using UnityEngine;

// Casts the fishing line when the trigger is pulled.
public class CastLine : MonoBehaviour
{
    public float castForce = 6f;

    public void Cast(Rigidbody lure)
    {
        lure.AddForce(transform.forward * castForce, ForceMode.Impulse);
    }
}
